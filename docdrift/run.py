"""One entry point used by the CLI, the GitHub Action and the MCP server."""
from __future__ import annotations

from pathlib import Path

from .config import settings
from .context import RunContext
from .graph import build_graph
from .publisher import publish


def run(repo: str, base: str = "HEAD~1", head: str = "HEAD", mode: str = "dry-run",
        out: str | None = None, quiet: bool = False, base_branch: str | None = None) -> dict:
    ctx = RunContext(repo=repo, base=base, head=head, quiet=quiet)
    ctx.emit("ChangeAnalyst", f"DocDrift run {ctx.base[:7]}..{ctx.head[:7]} on {ctx.repo.name} "
                              f"({'Claude ' + settings.model if ctx.llm.available else 'deterministic mode'})")
    graph = build_graph(ctx)
    state = graph.invoke({}, {"recursion_limit": 25})
    if not state.get("changeset") or not state["changeset"].changes:
        ctx.emit("Publisher", "No user-visible code changes; docs are in sync")
        return {"mode": mode, "files": [], "pr_url": None, "state": state, "ctx": ctx}
    out_dir = Path(out) if out else ctx.repo / ".docdrift" / "out"
    result = publish(ctx, state, mode, out_dir, base_branch)
    result.update(state=state, ctx=ctx)
    return result
