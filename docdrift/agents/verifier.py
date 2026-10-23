# Author: Thiraviam
# Agent 4 — Verifier
# Independently checks every patch against the NEW code before anything is published:
# guardrails, leftover stale identifiers, citation validity, hallucinated identifiers,
# code-snippet syntax, and (with an LLM) a semantic accuracy review. Failing patches go back
# to the Doc Fixer with concrete feedback, up to max_retries; then they're flagged for a human.
from __future__ import annotations

import ast
import re

from ..config import settings
from ..context import RunContext
from ..doc_index import code_mask, find_hits, looks_like_identifier, term_regex
from ..guardrails import check_patch
from ..schemas import DocSection, LLMSemanticCheck, Verdict
from ..state import DriftState

AGENT = "Verifier"

SYSTEM = """You are the Verifier. Compare the ORIGINAL and UPDATED documentation section with the
code evidence. Report concrete problems only: statements that contradict the code, stale
references left behind, invented identifiers/defaults, or unrelated content that was changed.
If the update is accurate and minimal, return accurate=true with no issues."""

CODE_SPAN_RE = re.compile(r"`([^`]+)`")
PATH_RE = re.compile(r"/v\d+/[A-Za-z0-9_\-/{}]+")
SNAKE_RE = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b|\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")


def _code_tokens(text: str) -> set[str]:
    """Identifier-like tokens that appear in code spans or fenced blocks."""
    toks: set[str] = set()
    mask = code_mask(text)
    for line, is_code in zip(text.splitlines(), mask):
        chunks = [line] if is_code else CODE_SPAN_RE.findall(line)
        for ch in chunks:
            toks |= set(SNAKE_RE.findall(ch))
            toks |= set(PATH_RE.findall(ch))
    return toks


def _python_blocks(text: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", text, flags=re.S)


def _route_ok(path: str, ctx: RunContext) -> bool:
    """A doc path like /v1/inventory/SKU-1001 is fine if it falls under a real route."""
    prefix = path.split("{")[0].rstrip("/")
    for s in ctx.code_vocab:
        if not s.startswith("/") or len(s) < 2:
            continue
        route_root = s.split("{")[0].rstrip("/")
        if len(route_root) > 1 and (s.startswith(prefix) or prefix.startswith(route_root)):
            return True
    return False


# Author: Thiraviam
def verifier(ctx: RunContext, state: DriftState) -> DriftState:
    cs = state["changeset"]
    by_id = {c.id: c for c in cs.changes}
    impacts = {i.section_id: i for i in state["impacts"]}
    verdicts = dict(state.get("verdicts", {}))
    feedback = dict(state.get("feedback", {}))
    retry: list[str] = []

    for sid in state.get("pending", []):
        section = ctx.index.by_id[sid]
        patch = state["patches"][sid]
        changes = [by_id[i] for i in impacts[sid].change_ids if i in by_id]
        issues = check_patch(section, patch)
        updated = DocSection(**{**section.model_dump(), "text": patch.updated})

        # 1. Stale references must be gone
        for ch in changes:
            if ch.kind == "default" or not ch.old or not ch.new:
                continue
            left = [h for h in find_hits(updated, ch.old) if h.in_code or looks_like_identifier(ch.old)]
            if left:
                issues.append(f"Still references old `{ch.old}` (should be `{ch.new}`): \"{left[0].line.strip()}\"")
        for ch in changes:
            if ch.kind == "default":
                names = {ch.context.split("@")[0]} | {c.old for c in cs.changes if c.kind == "parameter" and c.new == ch.context.split("@")[0]}
                for line in patch.updated.splitlines():
                    if term_regex(ch.old).search(line) and any(term_regex(n).search(line) for n in names if n):
                        issues.append(f"Default still shown as {ch.old} (now {ch.new}): \"{line.strip()}\"")

        # 2. Citations must point at real code that contains the symbol
        for c in patch.citations:
            src = ctx.code_files.get(c.file)
            if src is None:
                issues.append(f"Citation {c.file}:{c.line} - file not in repo")
                continue
            lines = src.splitlines()
            window = "\n".join(lines[max(0, c.line - 3): c.line + 2])
            if not (1 <= c.line <= len(lines)) or c.symbol.split("{")[0].strip("`") not in window:
                issues.append(f"Citation {c.file}:{c.line} does not contain `{c.symbol}`")

        # 3. No invented identifiers (anything new in code spans must exist in the codebase)
        introduced = _code_tokens(patch.updated) - _code_tokens(section.text)
        allowed = {c.new for c in changes if c.new}
        for tok in sorted(introduced):
            if tok in allowed or tok in ctx.code_vocab:
                continue
            if tok.startswith("/") and _route_ok(tok, ctx):
                continue
            issues.append(f"`{tok}` does not exist in the code (possible hallucination)")

        # 4. Python snippets must still parse
        for block in _python_blocks(patch.updated):
            try:
                ast.parse(block)
            except SyntaxError as e:
                issues.append(f"Python snippet no longer parses: {e.msg} (line {e.lineno})")

        # 5. Semantic review (LLM) once the deterministic checks pass
        if not issues and ctx.llm.available:
            evidence = "\n".join(ctx.code_lines(c.file, c.line) for c in changes)
            try:
                chk = ctx.llm.structured(
                    SYSTEM,
                    f"<doc original>\n{section.text}\n</doc>\n<doc updated>\n{patch.updated}\n</doc>\n"
                    f"Changes:\n" + "\n".join(f"- {c.description}" for c in changes) + f"\n<code>\n{evidence}\n</code>",
                    LLMSemanticCheck,
                )
                if not chk.accurate:
                    issues += [f"Semantic: {i}" for i in chk.issues] or ["Semantic: reviewer judged update inaccurate"]
            except Exception as e:
                ctx.emit(AGENT, f"Semantic check skipped for {sid} ({e.__class__.__name__})")

        attempt = state["attempts"].get(sid, 1)
        can_retry = ctx.llm.available and attempt <= settings.max_retries
        if not issues:
            status = "pass"
        elif can_retry:
            status = "retry"
            retry.append(sid)
        else:
            status = "needs_human"
        verdicts[sid] = Verdict(section_id=sid, status=status, issues=issues)
        feedback[sid] = issues
        icon = {"pass": "PASS ", "retry": "RETRY", "needs_human": "HUMAN"}[status]
        ctx.emit(AGENT, f"{icon} {sid}" + (f"  - {issues[0]}" if issues else ""))

    return {"verdicts": verdicts, "feedback": feedback, "pending": retry}
