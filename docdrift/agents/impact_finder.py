# Author: Thiraviam
# Agent 2 — Impact Finder
# Finds every doc section the ChangeSet made stale. Recall comes from three retrievers:
# exact symbol hits, long-term memory links, and BM25 over section text. Precision comes from
# Claude judging each candidate (or a context heuristic when no LLM is available).
from __future__ import annotations

from ..config import settings
from ..context import RunContext
from ..doc_index import find_hits, looks_like_identifier, term_regex
from ..guardrails import injection_flags
from ..llm import dumps
from ..schemas import Impact, LLMImpactBatch, SymbolChange
from ..state import DriftState

AGENT = "ImpactFinder"

SYSTEM = """You are the Impact Finder. For each candidate documentation section decide whether
the listed code changes make it STALE (it now describes behaviour that is no longer true).
A word match alone is not staleness: e.g. 'rate limit' prose is unrelated to a `limit` query
parameter. Return one judgement per candidate with a confidence 0-1 and the ids of the changes
that make it stale."""


def _param_aliases(ch: SymbolChange, changes: list[SymbolChange]) -> set[str]:
    name = ch.context.split("@")[0]
    names = {name}
    names |= {c.old for c in changes if c.kind == "parameter" and c.new == name and c.old}
    return names


def _score(ctx: RunContext, changes: list[SymbolChange]) -> dict[str, dict]:
    """Heuristic candidate scoring: section_id -> {change_ids, conf, evidence}."""
    cands: dict[str, dict] = {}

    def add(sid, cid, conf, why):
        c = cands.setdefault(sid, {"change_ids": set(), "conf": 0.0, "why": []})
        c["change_ids"].add(cid)
        c["conf"] = max(c["conf"], conf)
        c["why"].append(why)

    for ch in changes:
        if not ch.old:
            continue  # pure additions don't make existing docs wrong
        for s in ctx.index.sections:
            if ctx.memory.is_ignored(s.id, ch.old):
                continue
            if ch.kind == "default":
                names = _param_aliases(ch, changes)
                rx = term_regex(ch.old)
                lines = [l for l in s.text.splitlines() if rx.search(l) and any(term_regex(n).search(l) for n in names)]
                if lines:
                    add(s.id, ch.id, 0.85, f"default {ch.old} next to {'/'.join(sorted(names))}")
                continue
            hits = find_hits(s, ch.old)
            if not hits:
                continue
            if any(h.in_code for h in hits):
                add(s.id, ch.id, 0.9, f"`{ch.old}` in code context")
            elif looks_like_identifier(ch.old):
                add(s.id, ch.id, 0.8, f"identifier {ch.old} in prose")
            else:
                add(s.id, ch.id, 0.45, f"plain word '{ch.old}' in prose")
        for sid in ctx.memory.linked_sections(ch.old):
            if sid in ctx.index.by_id:
                add(sid, ch.id, 0.5, f"memory: previously linked to {ch.old}")
    return cands


# Author: Thiraviam
def impact_finder(ctx: RunContext, state: DriftState) -> DriftState:
    changes = state["changeset"].changes
    ctx.emit(AGENT, f"Indexed {len(ctx.index.sections)} doc sections across {len(ctx.doc_files)} files")
    cands = _score(ctx, changes)

    # Semantic recall: BM25 on change descriptions (LLM mode only — needs judgement)
    if ctx.llm.available:
        for ch in changes:
            for s, _ in ctx.index.search(f"{ch.description} {ch.old or ''}", k=2):
                if s.id not in cands:
                    cands[s.id] = {"change_ids": {ch.id}, "conf": 0.3, "why": ["bm25 semantic match"]}

    impacts: list[Impact] = []
    skipped: list[Impact] = []

    # Guardrail: sections that look like prompt injection are never sent for auto-fix
    for sid in list(cands):
        flags = injection_flags(ctx.index.by_id[sid].text)
        if flags:
            c = cands.pop(sid)
            skipped.append(Impact(section_id=sid, change_ids=sorted(c["change_ids"]), confidence=0,
                                  reason=f"needs human: possible prompt injection ({flags[0]})"))
            ctx.emit("Guardrail", f"{sid} contains instruction-like text; excluded from auto-fix")

    judged = False
    if ctx.llm.available and cands:
        try:
            payload = "\n\n".join(
                f'<doc id="{sid}">\n{ctx.index.by_id[sid].text}\n</doc>\nheuristic: {", ".join(c["why"])}'
                for sid, c in list(cands.items())[: settings.max_sections * 2]
            )
            batch = ctx.llm.structured(SYSTEM, f"Changes:\n{dumps(changes)}\n\nCandidates:\n{payload}", LLMImpactBatch)
            valid_ids = {c.id for c in changes}
            for j in batch.judgements:
                if j.section_id not in cands:
                    continue
                ids = [i for i in j.change_ids if i in valid_ids] or sorted(cands[j.section_id]["change_ids"])
                imp = Impact(section_id=j.section_id, change_ids=ids, confidence=j.confidence, reason=j.reason)
                (impacts if j.stale and j.confidence >= settings.impact_threshold else skipped).append(imp)
            judged = True
        except Exception as e:
            ctx.emit(AGENT, f"LLM judgement failed ({e.__class__.__name__}); falling back to heuristic")

    if not judged:
        for sid, c in cands.items():
            imp = Impact(section_id=sid, change_ids=sorted(c["change_ids"]), confidence=c["conf"],
                         reason="; ".join(dict.fromkeys(c["why"])))
            (impacts if c["conf"] >= settings.impact_threshold else skipped).append(imp)

    impacts.sort(key=lambda i: -i.confidence)
    if len(impacts) > settings.max_sections:
        overflow = impacts[settings.max_sections:]
        impacts = impacts[: settings.max_sections]
        for o in overflow:
            o.reason = "needs human: over max_sections budget; " + o.reason
        skipped += overflow
        ctx.emit("Guardrail", f"Capped auto-fix at {settings.max_sections} sections")

    for i in impacts:
        ctx.emit(AGENT, f"STALE  {i.section_id}  conf={i.confidence:.2f}  changes={i.change_ids}  ({i.reason})")
    for s in skipped:
        ctx.emit(AGENT, f"skip   {s.section_id}  conf={s.confidence:.2f}  ({s.reason})")

    return {"impacts": impacts, "skipped": skipped, "pending": [i.section_id for i in impacts]}
