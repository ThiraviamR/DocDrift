"""Run context shared by all agents (non-serialisable things live here, not in graph state)."""
from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import git_utils as g
from .code_facts import extract
from .doc_index import DocIndex, chunk
from .guardrails import path_allowed
from .llm import LLM
from .memory import Memory

COLORS = {
    "ChangeAnalyst": "\033[36m",
    "ImpactFinder": "\033[35m",
    "DocFixer": "\033[33m",
    "Verifier": "\033[32m",
    "Publisher": "\033[34m",
    "Guardrail": "\033[31m",
}
RESET = "\033[0m"


@dataclass
class RunContext:
    repo: Path
    base: str
    head: str
    llm: LLM = field(default_factory=LLM)
    quiet: bool = False
    started: float = field(default_factory=time.time)
    events: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.repo = Path(self.repo).resolve()
        self.base = g.resolve(self.repo, self.base)
        self.head = g.resolve(self.repo, self.head)
        self.memory = Memory(self.repo)
        files = g.ls_files(self.repo, self.head)
        self.code_files = {p: g.show(self.repo, self.head, p) or "" for p in files if g.is_code(p)}
        doc_paths = [p for p in files if g.is_doc(p) and path_allowed(p)]
        self.doc_files = {p: g.show(self.repo, self.head, p) or "" for p in doc_paths}
        self.index = DocIndex([s for p, c in self.doc_files.items() for s in chunk(p, c)])
        self.code_vocab = self._vocab()

    def _vocab(self) -> set[str]:
        vocab: set[str] = set()
        for src in self.code_files.values():
            f = extract(src)
            vocab |= f.identifiers | f.strings
            for s in f.strings:
                vocab |= set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", s))
        return vocab

    def code_lines(self, path: str, line: int | None, radius: int = 2) -> str:
        src = self.code_files.get(path, "")
        if not src or not line:
            return ""
        lines = src.splitlines()
        lo, hi = max(1, line - radius), min(len(lines), line + radius)
        return "\n".join(f"{i:>4}: {lines[i - 1]}" for i in range(lo, hi + 1))

    def emit(self, agent: str, msg: str, **data) -> dict:
        ev = {"t": round(time.time() - self.started, 2), "agent": agent, "msg": msg, **data}
        self.events.append(ev)
        if not self.quiet:
            c = COLORS.get(agent, "")
            print(f"{c}[{ev['t']:>5.1f}s] {agent:<13}{RESET} {msg}", file=sys.stderr, flush=True)
        return ev
