"""Markdown section index: heading-based chunking, exact-symbol lookup and BM25 retrieval."""
from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from .schemas import DocSection

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
TOKEN_RE = re.compile(r"[A-Za-z0-9_/{}\-]+")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"


def chunk(path: str, content: str) -> list[DocSection]:
    lines = content.splitlines()
    sections: list[DocSection] = []
    start, heading, in_fence = 1, "(top)", False
    used: dict[str, int] = {}

    def flush(end: int):
        if end < start:
            return
        body = "\n".join(lines[start - 1 : end])
        if not body.strip():
            return
        s = slug(heading)
        used[s] = used.get(s, 0) + 1
        sid = f"{path}#{s}" + (f"-{used[s]}" if used[s] > 1 else "")
        sections.append(DocSection(id=sid, path=path, heading=heading, start_line=start, end_line=end, text=body))

    for i, line in enumerate(lines, start=1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
        m = None if in_fence else HEADING_RE.match(line)
        if m:
            flush(i - 1)
            start, heading = i, m.group(2).strip()
    flush(len(lines))
    return sections


def term_regex(term: str) -> re.Pattern:
    """Whole-token match. Boundaries are only enforced on word-character ends, so '/v1/stock'
    still matches inside 'localhost:8000/v1/stock?x=1' (bug found in first demo run)."""
    word = re.compile(r"[A-Za-z0-9_]")
    pre = r"(?<![A-Za-z0-9_])" if word.match(term[:1]) else ""
    post = r"(?![A-Za-z0-9_])" if word.match(term[-1:]) else ""
    return re.compile(pre + re.escape(term) + post)


@dataclass
class Hit:
    line_no: int  # absolute line in file
    line: str
    in_code: bool


def code_mask(text: str) -> list[bool]:
    """Per line: True if the line is inside a fenced code block."""
    mask, fence = [], False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            fence = not fence
            mask.append(True)
            continue
        mask.append(fence)
    return mask


def in_inline_code(line: str, start: int) -> bool:
    return line[:start].count("`") % 2 == 1


def find_hits(section: DocSection, term: str) -> list[Hit]:
    rx = term_regex(term)
    hits = []
    mask = code_mask(section.text)
    for idx, line in enumerate(section.text.splitlines()):
        for m in rx.finditer(line):
            hits.append(Hit(section.start_line + idx, line, mask[idx] or in_inline_code(line, m.start())))
    return hits


def looks_like_identifier(term: str) -> bool:
    """INV_DB_URL, /v1/stock, page_size, getUser -> True; 'limit' -> False"""
    return bool(re.search(r"[_/.{}]|[a-z][A-Z]|^[A-Z0-9_]{3,}$", term))


class DocIndex:
    def __init__(self, sections: list[DocSection]):
        self.sections = sections
        self.by_id = {s.id: s for s in sections}
        corpus = [TOKEN_RE.findall(s.text.lower()) or ["_"] for s in sections]
        self._bm25 = BM25Okapi(corpus) if sections else None

    def search(self, query: str, k: int = 3) -> list[tuple[DocSection, float]]:
        if not self._bm25:
            return []
        scores = self._bm25.get_scores(TOKEN_RE.findall(query.lower()))
        ranked = sorted(zip(self.sections, scores), key=lambda x: -x[1])
        return [(s, float(sc)) for s, sc in ranked[:k] if sc > 0]
