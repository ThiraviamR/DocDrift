"""One entry point used by the CLI, the GitHub Action and the MCP server."""
from __future__ import annotations

from pathlib import Path

from . import git_utils as g
from .config import settings
from .context import RunContext
from .graph import build_graph
from .publisher import publish


class DocDriftError(RuntimeError):
    """A problem with the user's input or environment, with a message that says how to fix it."""


def _validate(repo: str, base: str, head: str) -> None:
    p = Path(repo)
    if not p.is_dir():
        raise DocDriftError(f"Repository path not found: {repo}")
    try:
        g.git(p, "rev-parse", "--git-dir")
    except RuntimeError:
        raise DocDriftError(f"{repo} is not a git repository") from None
    for ref in (base, head):
        try:
            g.resolve(p, ref + "^{commit}")
        except RuntimeError:
            raise DocDriftError(f"Unknown commit '{ref}' in {repo} (try HEAD~1, a branch name or a SHA)") from None


def run(repo: str, base: str = "HEAD~1", head: str = "HEAD", mode: str = "dry-run",
        out: str | None = None, quiet: bool = False, base_branch: str | None = None) -> dict:
    _validate(repo, base, head)
    ctx = RunContext(repo=repo, base=base, head=head, quiet=quiet)
    ctx.emit("ChangeAnalyst", f"DocDrift run {ctx.base[:7]}..{ctx.head[:7]} on {ctx.repo.name} "
                              f"({'Claude ' + settings.model if ctx.llm.available else 'deterministic mode'})")
    graph = build_graph(ctx)
    # recursion_limit is the hard stop on graph steps (the max_turns of the whole run);
    # max_retries and max_llm_calls bound the loop well before it is reached.
    state = graph.invoke({}, {"recursion_limit": 25})
    if getattr(ctx.llm, "disabled_reason", None):
        ctx.emit("Guardrail", f"Claude disabled mid-run ({ctx.llm.disabled_reason[:120]}); "
                              "finished with deterministic fallbacks")
    if not state.get("changeset") or not state["changeset"].changes:
        ctx.emit("Publisher", "No user-visible code changes; docs are in sync")
        return {"mode": mode, "files": [], "pr_url": None, "state": state, "ctx": ctx}
    out_dir = Path(out) if out else ctx.repo / ".docdrift" / "out"
    result = publish(ctx, state, mode, out_dir, base_branch)
    result.update(state=state, ctx=ctx)
    return result
