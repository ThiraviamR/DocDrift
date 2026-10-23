"""LangGraph wiring.

    START -> change_analyst --(no changes)--> finalize
                    |
               impact_finder --(nothing stale)--> finalize
                    |
                doc_fixer <------------------+
                    |                        | retry (max_retries, with feedback)
                 verifier -------------------+
                    |
                 finalize -> END   (publisher runs after the graph, see run.py)
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .agents.change_analyst import change_analyst
from .agents.doc_fixer import doc_fixer
from .agents.impact_finder import impact_finder
from .agents.verifier import verifier
from .context import RunContext
from .state import DriftState


def _finalize(ctx: RunContext, state: DriftState) -> DriftState:
    """Update long-term memory with confirmed doc<->code links."""
    verdicts = state.get("verdicts", {})
    by_id = {c.id: c for c in state["changeset"].changes} if state.get("changeset") else {}
    for imp in state.get("impacts", []):
        v = verdicts.get(imp.section_id)
        if v and v.status == "pass":
            for cid in imp.change_ids:
                ch = by_id.get(cid)
                if ch and ch.kind not in {"default", "constant"}:  # link identifiers, not bare values
                    ctx.memory.link(ch.new, imp.section_id)
    ctx.memory.log_run(ctx.head, {
        "changes": len(by_id),
        "stale": len(state.get("impacts", [])),
        "fixed": sum(1 for v in verdicts.values() if v.status == "pass"),
        "needs_human": sum(1 for v in verdicts.values() if v.status != "pass"),
    })
    ctx.memory.save()
    return {}


def build_graph(ctx: RunContext):
    sg = StateGraph(DriftState)
    sg.add_node("change_analyst", lambda s: change_analyst(ctx, s))
    sg.add_node("impact_finder", lambda s: impact_finder(ctx, s))
    sg.add_node("doc_fixer", lambda s: doc_fixer(ctx, s))
    sg.add_node("verifier", lambda s: verifier(ctx, s))
    sg.add_node("finalize", lambda s: _finalize(ctx, s))

    sg.add_edge(START, "change_analyst")
    sg.add_conditional_edges("change_analyst",
                             lambda s: "impact_finder" if s["changeset"].changes else "finalize")
    sg.add_conditional_edges("impact_finder", lambda s: "doc_fixer" if s.get("pending") else "finalize")
    sg.add_edge("doc_fixer", "verifier")
    sg.add_conditional_edges("verifier", lambda s: "doc_fixer" if s.get("pending") else "finalize")
    sg.add_edge("finalize", END)
    return sg.compile()
