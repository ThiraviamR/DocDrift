"""Runtime configuration. Everything is overridable via environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # optional
    pass


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes"}


@dataclass
class Settings:
    model: str = field(default_factory=lambda: os.getenv("DOCDRIFT_MODEL", "claude-sonnet-4-5"))
    api_key: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    force_mock: bool = field(default_factory=lambda: _env_bool("DOCDRIFT_MOCK", False))

    # Guardrails / budgets
    max_llm_calls: int = int(os.getenv("DOCDRIFT_MAX_LLM_CALLS", "40"))
    max_sections: int = int(os.getenv("DOCDRIFT_MAX_SECTIONS", "25"))
    max_retries: int = int(os.getenv("DOCDRIFT_MAX_RETRIES", "2"))
    impact_threshold: float = float(os.getenv("DOCDRIFT_IMPACT_THRESHOLD", "0.6"))
    max_changed_lines: int = int(os.getenv("DOCDRIFT_MAX_CHANGED_LINES", "40"))
    llm_timeout: float = float(os.getenv("DOCDRIFT_LLM_TIMEOUT", "60"))

    doc_globs: tuple[str, ...] = ("*.md", "docs/**/*.md")
    code_globs: tuple[str, ...] = ("*.py",)
    memory_dir: str = ".docdrift"

    @property
    def use_llm(self) -> bool:
        return bool(self.api_key) and not self.force_mock


settings = Settings()
