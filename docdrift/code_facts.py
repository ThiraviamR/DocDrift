"""Deterministic extraction of user-visible code facts (routes, params, defaults, env vars,
constants) from Python source, plus a diff between two versions.

This is the grounding layer: the LLM may add colour, but every change it reports and every
citation the Verifier checks traces back to facts extracted here.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from .schemas import SymbolChange

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


@dataclass
class Param:
    name: str
    default: str | None
    lineno: int


@dataclass
class Func:
    name: str
    lineno: int
    params: list[Param] = field(default_factory=list)
    route: tuple[str, str] | None = None  # (METHOD, path)
    route_line: int | None = None


@dataclass
class Facts:
    funcs: dict[str, Func] = field(default_factory=dict)
    env: dict[str, tuple[str, int]] = field(default_factory=dict)  # target var -> (ENV_NAME, line)
    consts: dict[str, tuple[str, int]] = field(default_factory=dict)  # NAME -> (repr value, line)
    identifiers: set[str] = field(default_factory=set)
    strings: set[str] = field(default_factory=set)


def _literal(node: ast.AST) -> str | None:
    try:
        return repr(ast.literal_eval(node))
    except Exception:
        return None


def _env_name(call: ast.AST) -> str | None:
    """os.getenv("X") / os.environ.get("X") / os.environ["X"]"""
    if isinstance(call, ast.Call):
        f = call.func
        name = ast.unparse(f)
        if name in {"os.getenv", "os.environ.get", "getenv"} and call.args:
            arg = call.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return arg.value
    if isinstance(call, ast.Subscript) and ast.unparse(call.value) == "os.environ":
        s = call.slice
        if isinstance(s, ast.Constant) and isinstance(s.value, str):
            return s.value
    return None


def extract(source: str) -> Facts:
    facts = Facts()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return facts

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            facts.identifiers.add(node.id)
        elif isinstance(node, ast.arg):
            facts.identifiers.add(node.arg)
        elif isinstance(node, ast.Attribute):
            facts.identifiers.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            facts.strings.add(node.value)

    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            env = _env_name(node.value)
            if env is None and isinstance(node.value, ast.Call):
                for sub in ast.walk(node.value):
                    env = _env_name(sub) or env
            if env:
                facts.env[target] = (env, node.lineno)
            elif target.isupper():
                val = _literal(node.value)
                if val is not None:
                    facts.consts[target] = (val, node.lineno)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            facts.funcs[node.name] = _func(node)
            facts.identifiers.add(node.name)
    # resolve defaults that reference module constants (limit: int = DEFAULT_PAGE_LIMIT)
    for fn in facts.funcs.values():
        for p in fn.params:
            if p.default in facts.consts:
                p.default = facts.consts[p.default][0]
    return facts


def _func(node) -> Func:
    fn = Func(name=node.name, lineno=node.lineno)
    args = node.args.args
    defaults = [None] * (len(args) - len(node.args.defaults)) + list(node.args.defaults)
    for a, d in zip(args, defaults):
        dval = None
        if d is not None:
            dval = _literal(d)
            if dval is None and isinstance(d, ast.Name):
                dval = d.id
        fn.params.append(Param(a.arg, dval, a.lineno))
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in HTTP_METHODS:
            if dec.args and isinstance(dec.args[0], ast.Constant):
                fn.route = (dec.func.attr.upper(), dec.args[0].value)
                fn.route_line = dec.lineno
    return fn


def static_prefix(path: str) -> str:
    """'/v1/stock/{sku}/reserve' -> '/v1/stock'"""
    out = []
    for seg in path.strip("/").split("/"):
        if seg.startswith("{"):
            break
        out.append(seg)
    return "/" + "/".join(out)


def _strip_quotes(v: str | None) -> str | None:
    if v and len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


def diff_facts(old: Facts, new: Facts, file: str) -> list[SymbolChange]:
    changes: list[SymbolChange] = []

    # Env vars: matched by the variable they are assigned to
    for target, (old_env, _) in old.env.items():
        if target in new.env and new.env[target][0] != old_env:
            env, line = new.env[target]
            changes.append(SymbolChange(kind="env_var", old=old_env, new=env, file=file, line=line,
                                        context=target, description=f"Env var {old_env} renamed to {env}"))
        elif target not in new.env:
            changes.append(SymbolChange(kind="env_var", old=old_env, new=None, file=file, line=None,
                                        context=target, description=f"Env var {old_env} no longer read"))

    prefix_seen: set[tuple[str, str]] = set()
    for name, of in old.funcs.items():
        nf = new.funcs.get(name)
        if nf is None:
            if of.route:
                changes.append(SymbolChange(kind="endpoint", old=of.route[1], new=None, file=file,
                                            context=name, description=f"{of.route[0]} {of.route[1]} removed"))
            continue
        ctx = f"{nf.route[0]} {nf.route[1]}" if nf.route else name

        # Route path change
        if of.route and nf.route and of.route != nf.route:
            changes.append(SymbolChange(kind="endpoint", old=of.route[1], new=nf.route[1], file=file,
                                        line=nf.route_line, context=name,
                                        description=f"{of.route[0]} {of.route[1]} is now {nf.route[0]} {nf.route[1]}"))
            op, np_ = static_prefix(of.route[1]), static_prefix(nf.route[1])
            if op != np_ and (op, np_) not in prefix_seen:
                prefix_seen.add((op, np_))
                changes.append(SymbolChange(kind="endpoint", old=op, new=np_, file=file, line=nf.route_line,
                                            context="path prefix", description=f"Path prefix {op} is now {np_}"))

        # Params: rename detection by position, then default changes
        old_p = {p.name: p for p in of.params}
        new_p = {p.name: p for p in nf.params}
        removed = [p for p in of.params if p.name not in new_p]
        added = [p for p in nf.params if p.name not in old_p]
        pairs: list[tuple[Param, Param]] = []
        for r in list(removed):
            idx = of.params.index(r)
            cand = next((a for a in added if nf.params.index(a) == idx), None)
            if cand:
                pairs.append((r, cand))
                removed.remove(r)
                added.remove(cand)
        for r, a in pairs:
            changes.append(SymbolChange(kind="parameter", old=r.name, new=a.name, file=file, line=a.lineno,
                                        context=ctx, description=f"Parameter `{r.name}` renamed to `{a.name}` on {ctx}"))
        for r in removed:
            changes.append(SymbolChange(kind="parameter", old=r.name, new=None, file=file, line=nf.lineno,
                                        context=ctx, description=f"Parameter `{r.name}` removed from {ctx}"))
        for a in added:
            changes.append(SymbolChange(kind="parameter", old=None, new=a.name, file=file, line=a.lineno,
                                        context=ctx, description=f"New parameter `{a.name}` on {ctx}"))
        for op_, np2 in [(old_p[n], new_p[n]) for n in old_p if n in new_p] + pairs:
            if op_.default != np2.default and op_.default is not None and np2.default is not None:
                changes.append(SymbolChange(
                    kind="default", old=_strip_quotes(op_.default), new=_strip_quotes(np2.default), file=file,
                    line=np2.lineno, context=f"{np2.name}@{ctx}",
                    description=f"Default of `{np2.name}` on {ctx} changed {op_.default} -> {np2.default}"))

    for name, nf in new.funcs.items():
        if name not in old.funcs and nf.route:
            changes.append(SymbolChange(kind="endpoint", old=None, new=nf.route[1], file=file, line=nf.route_line,
                                        context=name, description=f"New endpoint {nf.route[0]} {nf.route[1]}"))

    # Constants: renames (same value, one removed/one added) and value changes
    removed_c = {k: v for k, v in old.consts.items() if k not in new.consts}
    added_c = {k: v for k, v in new.consts.items() if k not in old.consts}
    for k, (val, _) in old.consts.items():
        if k in new.consts and new.consts[k][0] != val:
            changes.append(SymbolChange(kind="constant", old=k, new=k, file=file, line=new.consts[k][1],
                                        context=k, description=f"{k} changed {val} -> {new.consts[k][0]}"))
    if len(removed_c) == 1 and len(added_c) == 1:
        (ok, (ov, _)), (nk, (nv, nl)) = next(iter(removed_c.items())), next(iter(added_c.items()))
        changes.append(SymbolChange(kind="constant", old=ok, new=nk, file=file, line=nl, context=nk,
                                    description=f"Constant {ok}={ov} replaced by {nk}={nv}"))

    # Dedupe identical (kind, old, new) — e.g. a path-prefix change equal to a route change
    seen: dict[tuple, SymbolChange] = {}
    for c in changes:
        key = (c.kind, c.old, c.new)
        if key not in seen or seen[key].context == "path prefix":
            seen[key] = c
    return list(seen.values())


IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
