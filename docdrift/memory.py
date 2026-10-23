"""Long-term memory: a doc<->code map that improves with every run, stored in the target repo
at .docdrift/memory.json so it is versioned alongside the docs.

- links:   symbol -> {section_id: times confirmed}  (boosts recall next time)
- ignores: section_id -> [symbols]                  (human-confirmed false positives)
- runs:    short audit log of previous runs
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import settings


class Memory:
    def __init__(self, repo: str | Path):
        self.path = Path(repo) / settings.memory_dir / "memory.json"
        self.data = {"links": {}, "ignores": {}, "runs": []}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text()))
            except json.JSONDecodeError:
                pass  # corrupt memory must never break a run

    def linked_sections(self, symbol: str) -> list[str]:
        return list(self.data["links"].get(symbol, {}))

    def is_ignored(self, section_id: str, symbol: str) -> bool:
        return symbol in self.data["ignores"].get(section_id, [])

    def link(self, symbol: str | None, section_id: str) -> None:
        if not symbol:
            return
        bucket = self.data["links"].setdefault(symbol, {})
        bucket[section_id] = bucket.get(section_id, 0) + 1

    def ignore(self, section_id: str, symbol: str) -> None:
        lst = self.data["ignores"].setdefault(section_id, [])
        if symbol not in lst:
            lst.append(symbol)

    def log_run(self, head: str, summary: dict) -> None:
        self.data["runs"] = (self.data["runs"] + [
            {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "head": head[:12], **summary}
        ])[-20:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))
