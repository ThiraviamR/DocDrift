"""Small git helpers (shelling out keeps dependencies at zero)."""
from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path


def git(repo: str | Path, *args: str, check: bool = True) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def resolve(repo, ref: str) -> str:
    return git(repo, "rev-parse", ref).strip()


def changed_files(repo, base: str, head: str) -> list[str]:
    return [l for l in git(repo, "diff", "--name-only", base, head).splitlines() if l]


def show(repo, ref: str, path: str) -> str | None:
    out = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{path}"], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else None


def ls_files(repo, ref: str) -> list[str]:
    return [l for l in git(repo, "ls-tree", "-r", "--name-only", ref).splitlines() if l]


def diff_text(repo, base: str, head: str, paths: list[str]) -> str:
    if not paths:
        return ""
    return git(repo, "diff", "--unified=3", base, head, "--", *paths)


def matches(path: str, globs) -> bool:
    name = Path(path).name
    for g in globs:
        if fnmatch.fnmatch(path, g):
            return True
        if "/" not in g and fnmatch.fnmatch(name, g) and "/" not in path:
            return True
    return False


def is_code(path: str) -> bool:
    return path.endswith(".py")


def is_doc(path: str) -> bool:
    return path.endswith(".md")
