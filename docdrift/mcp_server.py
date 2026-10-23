"""DocDrift as an MCP server, so any MCP client (Claude Desktop, Claude Code, Cursor) can ask
"are my docs stale after this change?" as a tool call.

Run:  python -m docdrift.mcp_server
Claude Desktop config:
  {"mcpServers": {"docdrift": {"command": "python", "args": ["-m", "docdrift.mcp_server"],
                               "env": {"ANTHROPIC_API_KEY": "..."}}}}
"""
from __future__ import annotations

from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .run import run

mcp = _Server("docdrift")


@mcp.tool()
def check_docs(repo: str, base: str = "HEAD~1", head: str = "HEAD") -> str:
    """Find documentation made stale by the code changes between base and head, and return a
    report with proposed, verified fixes. Read-only: the repository is not modified."""
    res = run(repo, base, head, mode="dry-run", quiet=True)
    if not res.get("report"):
        return "No user-visible code changes; docs are in sync."
    return Path(res["report"]).read_text()


@mcp.tool()
def apply_doc_fixes(repo: str, base: str = "HEAD~1", head: str = "HEAD") -> str:
    """Apply verified documentation fixes to the working tree (markdown files only)."""
    res = run(repo, base, head, mode="apply", quiet=True)
    return f"Updated: {', '.join(res['files']) or 'nothing'}"


@mcp.tool()
def ignore_section(repo: str, section_id: str, symbol: str) -> str:
    """Record in long-term memory that a doc section is a false positive for a symbol."""
    from .memory import Memory

    m = Memory(repo)
    m.ignore(section_id, symbol)
    m.save()
    return f"Will ignore {section_id} for `{symbol}` from now on."


if __name__ == "__main__":
    mcp.run()
