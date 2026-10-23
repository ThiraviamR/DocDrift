"""DocDrift as an MCP server, so any MCP client (Claude Desktop, Claude Code, Cursor) can ask
"are my docs stale after this change?" as a tool call.

Run:  python -m docdrift.mcp_server
Claude Desktop config:
  {"mcpServers": {"docdrift": {"command": "python", "args": ["-m", "docdrift.mcp_server"],
                               "env": {"ANTHROPIC_API_KEY": "..."}}}}
"""
from __future__ import annotations

import functools
from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .run import run

mcp = _Server("docdrift")


def _safe(fn):
    """Return failures as a readable tool result instead of a stack trace, so the calling model
    can tell the user what to fix (wrong path, unknown commit, ...)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - tool boundary
            return f"DocDrift error ({e.__class__.__name__}): {e}"
    return wrapper


@mcp.tool()
@_safe
def check_docs(repo: str, base: str = "HEAD~1", head: str = "HEAD") -> str:
    """Find documentation made stale by the code changes between base and head, and return a
    report with proposed, verified fixes. Docs are not modified; the report and DocDrift's
    memory are written under <repo>/.docdrift/."""
    res = run(repo, base, head, mode="dry-run", quiet=True)
    if not res.get("report"):
        return "No user-visible code changes; docs are in sync."
    return Path(res["report"]).read_text()


@mcp.tool()
@_safe
def apply_doc_fixes(repo: str, base: str = "HEAD~1", head: str = "HEAD") -> str:
    """Apply verified documentation fixes to the working tree (markdown files only)."""
    res = run(repo, base, head, mode="apply", quiet=True)
    return f"Updated: {', '.join(res['files']) or 'nothing'}"


@mcp.tool()
@_safe
def ignore_section(repo: str, section_id: str, symbol: str) -> str:
    """Record in long-term memory that a doc section is a false positive for a symbol."""
    from .memory import Memory

    m = Memory(repo)
    m.ignore(section_id, symbol)
    m.save()
    return f"Will ignore {section_id} for `{symbol}` from now on."


if __name__ == "__main__":
    mcp.run()
