# Author: Thiraviam
# Agent 3 — Doc Fixer
# Rewrites only the stale sections, with minimal edits, citing the code line behind each fix.
# On retry it receives the Verifier's feedback for that section (Verifier -> Fixer loop).
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..context import RunContext
from ..doc_index import code_mask, in_inline_code, looks_like_identifier, term_regex
from ..llm import dumps
from ..schemas import Citation, DocPatch, DocSection, SymbolChange
from ..state import DriftState

AGENT = "DocFixer"

SYSTEM = """You are the Doc Fixer. Rewrite the given markdown section so it is accurate for the
NEW code. Rules:
- Minimal edit: change only what the code changes require; keep tone, structure and formatting.
- Keep the heading line exactly as is.
- Use only identifiers, paths, env vars and defaults that appear in the provided code facts.
- Update prose that describes the changed thing too (e.g. 'the TTL' when `ttl_minutes` was renamed).
- Cite every fix: file, line and the new symbol, using the numbered code evidence provided.
- If a verifier left feedback, fix exactly those problems."""


class _LLMFix(BaseModel):
    updated: str = Field(description="Full replacement markdown for the section, heading line included")
    citations: list[Citation]
    rationale: str


def _deterministic_fix(section: DocSection, changes: list[SymbolChange], all_changes) -> DocPatch:
    """No-LLM fallback: token-level replacement in code contexts and identifier-like prose."""
    lines = section.text.splitlines()
    mask = code_mask(section.text)
    cites: list[Citation] = []
    renames = sorted([c for c in changes if c.old and c.new and c.kind != "default"], key=lambda c: -len(c.old))
    defaults = [c for c in changes if c.kind == "default"]

    for idx, line in enumerate(lines):
        new_line = line
        for ch in renames:
            rx = term_regex(ch.old)

            def repl(m, ch=ch, src=new_line):
                ok = mask[idx] or in_inline_code(src, m.start()) or looks_like_identifier(ch.old)
                return ch.new if ok else m.group(0)

            replaced = rx.sub(repl, new_line)
            if replaced != new_line:
                cites.append(Citation(file=ch.file, line=ch.line or 1, symbol=ch.new))
                new_line = replaced
        for ch in defaults:
            pname = ch.context.split("@")[0]
            names = {pname} | {c.old for c in all_changes if c.kind == "parameter" and c.new == pname and c.old}
            if any(term_regex(n).search(new_line) for n in names) and term_regex(ch.old).search(new_line):
                new_line = term_regex(ch.old).sub(ch.new, new_line)
                cites.append(Citation(file=ch.file, line=ch.line or 1, symbol=pname))
        lines[idx] = new_line

    updated = "\n".join(lines)
    uniq = list({(c.file, c.line, c.symbol): c for c in cites}.values())
    return DocPatch(section_id=section.id, updated=updated, citations=uniq,
                    rationale="Deterministic rename of changed identifiers (no LLM configured).")


# Author: Thiraviam
def doc_fixer(ctx: RunContext, state: DriftState) -> DriftState:
    cs = state["changeset"]
    by_id = {c.id: c for c in cs.changes}
    impacts = {i.section_id: i for i in state["impacts"]}
    attempts = dict(state.get("attempts", {}))
    patches = dict(state.get("patches", {}))

    for sid in state.get("pending", []):
        section = ctx.index.by_id[sid]
        changes = [by_id[i] for i in impacts[sid].change_ids if i in by_id]
        attempts[sid] = attempts.get(sid, 0) + 1
        feedback = state.get("feedback", {}).get(sid, [])
        patch = None

        if ctx.llm.available:
            evidence = "\n\n".join(
                f"change #{c.id}: {c.description}\n<code file=\"{c.file}\">\n{ctx.code_lines(c.file, c.line)}\n</code>"
                for c in changes
            )
            fb = ("\n\nVerifier feedback from your previous attempt:\n- " + "\n- ".join(feedback)) if feedback else ""
            prev = f"\n\nYour previous attempt:\n<doc>\n{patches[sid].updated}\n</doc>" if sid in patches and feedback else ""
            try:
                out = ctx.llm.structured(
                    SYSTEM,
                    f"Section ({sid}):\n<doc>\n{section.text}\n</doc>\n\nCode facts:\n{dumps(changes)}\n\n"
                    f"Code evidence:\n{evidence}{prev}{fb}",
                    _LLMFix,
                )
                patch = DocPatch(section_id=sid, updated=out.updated.rstrip("\n"), citations=out.citations,
                                 rationale=out.rationale, attempt=attempts[sid])
            except Exception as e:
                ctx.emit(AGENT, f"LLM fix failed for {sid} ({e.__class__.__name__}); using deterministic fix")

        if patch is None:
            patch = _deterministic_fix(section, changes, cs.changes)
            patch.attempt = attempts[sid]

        patches[sid] = patch
        tag = f" (retry {attempts[sid] - 1})" if attempts[sid] > 1 else ""
        ctx.emit(AGENT, f"Patched {sid}{tag}: {len(patch.citations)} citation(s)")

    return {"patches": patches, "attempts": attempts}
