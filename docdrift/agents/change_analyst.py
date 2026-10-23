# Author: Thiraviam
# Agent 1 — Change Analyst
# Reads the git diff between base and head and produces a typed ChangeSet of user-visible
# changes. Deterministic AST diff is the source of truth; Claude adds a plain-English summary
# and may propose extra behaviour changes, which are kept only if grounded in the source.
from __future__ import annotations

from .. import git_utils as g
from ..code_facts import diff_facts, extract
from ..context import RunContext
from ..llm import dumps
from ..schemas import ChangeSet, LLMChangeNotes
from ..state import DriftState

AGENT = "ChangeAnalyst"

SYSTEM = """You are the Change Analyst. Given a code diff and a list of changes already extracted
by static analysis, write a short summary for API users and list any ADDITIONAL user-visible
changes (behaviour, status codes, response fields) that the list misses. Only report what the
diff proves. Use exact identifiers from the code."""


# Author: Thiraviam
def change_analyst(ctx: RunContext, state: DriftState) -> DriftState:
    files = g.changed_files(ctx.repo, ctx.base, ctx.head)
    code = [f for f in files if g.is_code(f)]
    ctx.emit(AGENT, f"{len(files)} files changed, {len(code)} code files: {', '.join(code) or '-'}")

    changes = []
    old_src, new_src = {}, {}
    for f in code:
        old_src[f] = g.show(ctx.repo, ctx.base, f) or ""
        new_src[f] = g.show(ctx.repo, ctx.head, f) or ""
        changes += diff_facts(extract(old_src[f]), extract(new_src[f]), f)

    summary = f"{len(changes)} user-visible change(s) detected by static analysis."
    if ctx.llm.available and code:
        try:
            diff = g.diff_text(ctx.repo, ctx.base, ctx.head, code)[:15000]
            notes = ctx.llm.structured(
                SYSTEM,
                f"<diff>\n{diff}\n</diff>\n\nAlready extracted:\n{dumps(changes)}",
                LLMChangeNotes,
            )
            summary = notes.summary
            for extra in notes.extra_changes:
                grounded = extra.file in code and (
                    (extra.old and extra.old in old_src[extra.file])
                    or (extra.new and extra.new in new_src[extra.file])
                )
                if grounded:
                    changes.append(extra)
                    ctx.emit(AGENT, f"LLM added: {extra.description}")
                else:
                    ctx.emit("Guardrail", f"Dropped ungrounded LLM change: {extra.description}")
        except Exception as e:  # LLM trouble must not stop the pipeline
            ctx.emit(AGENT, f"LLM summary skipped ({e.__class__.__name__}); using static analysis only")

    for i, c in enumerate(changes, start=1):
        c.id = i
        ctx.emit(AGENT, f"  #{i} {c.kind:<9} {c.old} -> {c.new}")

    cs = ChangeSet(base=ctx.base, head=ctx.head, code_files=code, changes=changes, summary=summary)
    return {"changeset": cs, "attempts": {}, "feedback": {}, "patches": {}, "verdicts": {}}
