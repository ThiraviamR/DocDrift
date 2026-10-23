"""LangGraph state. Short-term memory for one run: everything agents hand to each other."""
from __future__ import annotations

from typing import TypedDict

from .schemas import ChangeSet, DocPatch, Impact, Verdict


class DriftState(TypedDict, total=False):
    changeset: ChangeSet
    impacts: list[Impact]
    skipped: list[Impact]
    pending: list[str]  # section ids the Fixer must (re)work this round
    attempts: dict[str, int]
    feedback: dict[str, list[str]]  # Verifier -> Fixer notes per section
    patches: dict[str, DocPatch]
    verdicts: dict[str, Verdict]
    result: dict
