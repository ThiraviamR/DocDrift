"""Typed contracts passed between agents. Every handoff is one of these models."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ChangeKind = Literal["endpoint", "parameter", "default", "env_var", "function", "constant", "other"]


class SymbolChange(BaseModel):
    id: int = 0
    kind: ChangeKind
    old: str | None = Field(None, description="Old identifier/value as it would appear in docs")
    new: str | None = Field(None, description="New identifier/value; null if removed")
    file: str
    line: int | None = Field(None, description="Line in the NEW file that proves the change")
    context: str = Field("", description="Owning function/route, e.g. 'list_stock' or 'GET /v1/inventory'")
    description: str = ""


class ChangeSet(BaseModel):
    base: str
    head: str
    code_files: list[str]
    changes: list[SymbolChange]
    summary: str = ""


class DocSection(BaseModel):
    id: str  # "<path>#<slug>"
    path: str
    heading: str
    start_line: int  # 1-based, inclusive
    end_line: int  # inclusive
    text: str


class Impact(BaseModel):
    section_id: str
    change_ids: list[int]
    confidence: float
    reason: str


class ImpactReport(BaseModel):
    impacts: list[Impact]
    skipped: list[Impact] = []  # candidates judged not stale (false positives)


class Citation(BaseModel):
    file: str
    line: int
    symbol: str


class DocPatch(BaseModel):
    section_id: str
    updated: str = Field(description="Full replacement markdown for the section, heading included")
    citations: list[Citation]
    rationale: str
    attempt: int = 1


class Verdict(BaseModel):
    section_id: str
    status: Literal["pass", "retry", "needs_human"]
    issues: list[str] = []


# ---- LLM output shapes (kept small so structured output stays reliable) ----

class LLMChangeNotes(BaseModel):
    summary: str = Field(description="2-3 sentence plain-English summary of what changed for API users")
    extra_changes: list[SymbolChange] = Field(
        default_factory=list,
        description="User-visible behaviour changes NOT already in the provided list (empty if none)",
    )


class LLMImpactJudgement(BaseModel):
    section_id: str
    stale: bool
    confidence: float = Field(ge=0, le=1)
    change_ids: list[int]
    reason: str


class LLMImpactBatch(BaseModel):
    judgements: list[LLMImpactJudgement]


class LLMSemanticCheck(BaseModel):
    accurate: bool
    issues: list[str] = Field(default_factory=list, description="Concrete problems; empty if accurate")
