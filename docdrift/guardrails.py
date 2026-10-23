"""Deterministic guardrails. These run regardless of what the LLM says."""
from __future__ import annotations

import difflib
import re

from .config import settings
from .schemas import DocPatch, DocSection

SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
INJECTION_PATTERNS = [
    re.compile(r"ignore (all |any )?(previous|prior|above) instructions", re.I),
    re.compile(r"you are now", re.I),
    re.compile(r"system prompt", re.I),
]
DENY_PATH_PARTS = (".github/", ".docdrift/", "node_modules/", ".venv/")


def path_allowed(path: str) -> bool:
    """DocDrift may only ever write markdown docs - never code, CI, or its own memory."""
    return path.endswith(".md") and not any(p in path for p in DENY_PATH_PARTS)


def changed_line_count(before: str, after: str) -> int:
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
    return sum(1 for l in diff if l[:1] in "+-" and not l.startswith(("+++", "---")))


def check_patch(section: DocSection, patch: DocPatch) -> list[str]:
    issues: list[str] = []
    if not path_allowed(section.path):
        issues.append(f"GUARDRAIL: {section.path} is not an editable doc path")
    first_before = section.text.splitlines()[0] if section.text else ""
    first_after = patch.updated.splitlines()[0] if patch.updated else ""
    if first_before.startswith("#") and first_before.strip() != first_after.strip():
        issues.append("GUARDRAIL: section heading was changed or removed")
    n = changed_line_count(section.text, patch.updated)
    if n == 0:
        issues.append("GUARDRAIL: patch makes no change")
    if n > settings.max_changed_lines:
        issues.append(f"GUARDRAIL: patch changes {n} lines (limit {settings.max_changed_lines})")
    for rx in SECRET_PATTERNS:
        if rx.search(patch.updated) and not rx.search(section.text):
            issues.append("GUARDRAIL: patch introduces something that looks like a secret")
    if not patch.citations:
        issues.append("GUARDRAIL: patch has no code citations")
    return issues


def injection_flags(text: str) -> list[str]:
    return [rx.pattern for rx in INJECTION_PATTERNS if rx.search(text)]
