"""docdrift CLI

  python -m docdrift run --repo PATH [--base HEAD~1] [--head HEAD] [--mode dry-run|apply|branch|pr]
  python -m docdrift demo            # build sample repo, make a breaking change, run DocDrift
  python -m docdrift ignore --repo PATH --section docs/runbook.md#x --symbol limit
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="docdrift", description="Keep docs in sync with code.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Check a commit range and fix stale docs")
    r.add_argument("--repo", default=".")
    r.add_argument("--base", default="HEAD~1")
    r.add_argument("--head", default="HEAD")
    r.add_argument("--mode", choices=["dry-run", "apply", "branch", "pr"], default="dry-run")
    r.add_argument("--out", default=None, help="Report directory (default: <repo>/.docdrift/out)")
    r.add_argument("--base-branch", default=None, help="PR target branch (default: main)")
    r.add_argument("--mock", action="store_true", help="Force deterministic mode (no LLM calls)")

    d = sub.add_parser("demo", help="End-to-end demo on the bundled sample app")
    d.add_argument("--dir", default=str(ROOT / "demo_repo"))
    d.add_argument("--mock", action="store_true")

    ig = sub.add_parser("ignore", help="Teach memory that a section is a false positive for a symbol")
    ig.add_argument("--repo", default=".")
    ig.add_argument("--section", required=True)
    ig.add_argument("--symbol", required=True)

    a = ap.parse_args(argv)
    if getattr(a, "mock", False):
        os.environ["DOCDRIFT_MOCK"] = "1"
        from .config import settings
        settings.force_mock = True

    if a.cmd == "ignore":
        from .memory import Memory
        m = Memory(a.repo)
        m.ignore(a.section, a.symbol)
        m.save()
        print(f"Memory updated: {a.section} will be ignored for `{a.symbol}`")
        return 0

    from .run import run

    if a.cmd == "demo":
        subprocess.run(["bash", str(ROOT / "demo" / "setup_demo.sh"), a.dir], check=True)
        subprocess.run(["bash", str(ROOT / "demo" / "make_change.sh"), a.dir], check=True)
        res = run(a.dir, "HEAD~1", "HEAD", mode="apply", out=str(Path(a.dir) / ".docdrift" / "out"))
    else:
        res = run(a.repo, a.base, a.head, mode=a.mode, out=a.out, base_branch=a.base_branch)

    st = res["state"]
    v = st.get("verdicts", {})
    fixed = sum(1 for x in v.values() if x.status == "pass")
    human = len(v) - fixed
    print(f"\nDocDrift: {len(st.get('impacts', []))} stale section(s), {fixed} fixed, {human} need human.")
    if res.get("report"):
        print(f"Report: {res['report']}")
    if res.get("pr_url"):
        print(f"PR: {res['pr_url']}")
    return 0 if human == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
