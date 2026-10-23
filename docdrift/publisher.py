"""Publisher: applies verified patches and ships them.

Modes
- dry-run : write report + unified patch to --out; repo untouched (default, demo-safe)
- apply   : write fixed docs into the working tree
- branch  : commit to docdrift/<sha> via a temporary git worktree (your checkout is untouched)
- pr      : branch + push + open a GitHub PR (needs GITHUB_TOKEN and a github.com origin)

Never merges. Never touches non-markdown files (guardrails.path_allowed).
"""
from __future__ import annotations

import difflib
import json
import os
import re
import tempfile
import urllib.request
from pathlib import Path

from . import git_utils as g
from .context import RunContext
from .guardrails import path_allowed
from .state import DriftState

AGENT = "Publisher"


def build_files(ctx: RunContext, state: DriftState) -> dict[str, str]:
    """Return {path: new_content} for every doc with at least one passing patch."""
    passing = [p for sid, p in state.get("patches", {}).items() if state["verdicts"].get(sid) and state["verdicts"][sid].status == "pass"]
    by_path: dict[str, list] = {}
    for p in passing:
        s = ctx.index.by_id[p.section_id]
        by_path.setdefault(s.path, []).append((s, p))
    out = {}
    for path, items in by_path.items():
        if not path_allowed(path):
            continue
        original = ctx.doc_files[path]
        lines = original.splitlines()
        for s, p in sorted(items, key=lambda x: -x[0].start_line):
            old_block = lines[s.start_line - 1 : s.end_line]
            trailing = 0
            while trailing < len(old_block) and not old_block[-1 - trailing].strip():
                trailing += 1
            new_lines = p.updated.rstrip().splitlines()
            lines[s.start_line - 1 : s.end_line] = new_lines + [""] * trailing
        out[path] = "\n".join(lines) + ("\n" if original.endswith("\n") else "")
    return out


def unified_patch(ctx: RunContext, files: dict[str, str]) -> str:
    chunks = []
    for path, new in files.items():
        chunks += difflib.unified_diff(ctx.doc_files[path].splitlines(True), new.splitlines(True),
                                       fromfile=f"a/{path}", tofile=f"b/{path}")
    return "".join(chunks)


def report_md(ctx: RunContext, state: DriftState, patch: str) -> str:
    cs = state["changeset"]
    verdicts = state.get("verdicts", {})
    passed = [v for v in verdicts.values() if v.status == "pass"]
    human = [v for v in verdicts.values() if v.status != "pass"]
    skipped = state.get("skipped", [])
    impacts = {i.section_id: i for i in state.get("impacts", [])}
    patches = state.get("patches", {})
    L = [
        "## DocDrift: documentation updates",
        "",
        f"Code change `{cs.base[:7]}..{cs.head[:7]}` made **{len(impacts)} doc section(s)** stale. "
        f"**{len(passed)} fixed and verified**, **{len(human)} need a human**.",
        "",
        f"> {cs.summary}",
        "",
        "### Code changes detected",
        "",
        "| # | Kind | Old | New | Evidence |",
        "|---|---|---|---|---|",
    ]
    for c in cs.changes:
        L.append(f"| {c.id} | {c.kind} | `{c.old}` | `{c.new}` | `{c.file}:{c.line}` |")
    if passed:
        L += ["", "### Fixed sections", ""]
        for v in passed:
            p, i = patches[v.section_id], impacts[v.section_id]
            cites = ", ".join(f"`{c.file}:{c.line}`" for c in p.citations)
            L.append(f"- **{v.section_id}** (confidence {i.confidence:.2f}, attempt {p.attempt}): {i.reason}. Evidence: {cites}")
    if human:
        L += ["", "### Needs human review", ""]
        for v in human:
            L.append(f"- [ ] **{v.section_id}**: " + "; ".join(v.issues[:3]))
    if skipped:
        L += ["", "<details><summary>Candidates judged not stale</summary>", ""]
        for s in skipped:
            L.append(f"- {s.section_id} (conf {s.confidence:.2f}): {s.reason}")
        L += ["", "</details>"]
    if patch:
        L += ["", "<details><summary>Diff</summary>", "", "```diff", patch.rstrip(), "```", "", "</details>"]
    L += ["", f"_LLM calls: {ctx.llm.calls} · mode: {'claude' if ctx.llm.available else 'deterministic'} · "
              "DocDrift never merges; review and merge this PR yourself._"]
    return "\n".join(L)


def _github_repo(remote: str) -> tuple[str, str] | None:
    m = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", remote.strip())
    return (m.group(1), m.group(2)) if m else None


def _open_pr(owner: str, repo: str, head_branch: str, base_branch: str, title: str, body: str) -> str:
    token = os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        data=json.dumps({"title": title, "head": head_branch, "base": base_branch, "body": body}).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["html_url"]


def publish(ctx: RunContext, state: DriftState, mode: str, out_dir: Path, base_branch: str | None = None) -> dict:
    files = build_files(ctx, state)
    patch = unified_patch(ctx, files)
    body = report_md(ctx, state, patch)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "docdrift_report.md").write_text(body)
    (out_dir / "docdrift.patch").write_text(patch)
    (out_dir / "trace.json").write_text(json.dumps(ctx.events, indent=2, default=str))
    result = {"mode": mode, "files": sorted(files), "report": str(out_dir / "docdrift_report.md"), "pr_url": None}
    ctx.emit(AGENT, f"Report written to {out_dir / 'docdrift_report.md'}")

    if not files:
        ctx.emit(AGENT, "No verified fixes to publish")
        return result

    if mode == "apply":
        for path, content in files.items():
            (ctx.repo / path).write_text(content)
        ctx.emit(AGENT, f"Applied fixes to {len(files)} file(s) in working tree")

    elif mode in {"branch", "pr"}:
        branch = f"docdrift/{ctx.head[:7]}"
        wt = Path(tempfile.mkdtemp(prefix="docdrift-wt-"))
        g.git(ctx.repo, "worktree", "add", "-q", "-B", branch, str(wt), ctx.head)
        try:
            for path, content in files.items():
                (wt / path).write_text(content)
            g.git(wt, "add", *files)
            # Long-term memory travels with the PR so CI runs learn too
            if ctx.memory.path.exists():
                mem_rel = ctx.memory.path.relative_to(ctx.repo)
                (wt / mem_rel).parent.mkdir(parents=True, exist_ok=True)
                (wt / mem_rel).write_text(ctx.memory.path.read_text())
                g.git(wt, "add", "-f", str(mem_rel))
            g.git(wt, "-c", "user.name=DocDrift", "-c", "user.email=docdrift@users.noreply.github.com",
                  "commit", "-q", "-m", f"docs: sync documentation with {ctx.head[:7]} [docdrift]")
            ctx.emit(AGENT, f"Committed {len(files)} file(s) to branch {branch}")
            if mode == "pr":
                gh = _github_repo(g.git(ctx.repo, "remote", "get-url", "origin", check=False))
                if not gh or not os.getenv("GITHUB_TOKEN"):
                    ctx.emit(AGENT, "No github.com origin or GITHUB_TOKEN; stopping at branch")
                else:
                    g.git(wt, "push", "-q", "-f", "origin", branch)
                    base_b = base_branch or os.getenv("DOCDRIFT_BASE_BRANCH", "main")
                    result["pr_url"] = _open_pr(*gh, branch, base_b, f"docs: DocDrift sync for {ctx.head[:7]}", body)
                    ctx.emit(AGENT, f"Opened PR {result['pr_url']}")
        finally:
            g.git(ctx.repo, "worktree", "remove", "--force", str(wt), check=False)
        result["branch"] = branch
    return result
