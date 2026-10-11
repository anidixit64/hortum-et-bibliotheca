"""Generation: one request in, schema-checked JSON out, from whichever backend a chain picks.

A *chain* is an ordered list of backends for one tier ("light" for small jobs like clue
cleanup, "writing" for the summary and long sections). The worker tries them in order: a
quota or rate-limit error moves on to the next; if all are out, the job waits until the
earliest reset. ``CONTENT_USE_CLAUDE_CODE=false`` takes Claude Code out of every chain, so
everything runs on Gemini (and the worker can run in Docker).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class Request:
    task: str  # e.g. "clue_cleanup", for logs and stored results
    system: str
    prompt: str
    schema: dict[str, Any]  # JSON Schema the reply must match


@dataclass
class Reply:
    data: dict[str, Any]
    backend: str  # "claude_code" | "gemini"
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class GenerationError(Exception):
    """The backend answered but the answer was unusable (bad JSON, refusal, …)."""


class QuotaExceeded(Exception):
    """Rate-limited or out of quota: try the next backend, or wait until ``retry_at``."""

    def __init__(self, message: str, retry_at: datetime | None = None) -> None:
        super().__init__(message)
        self.retry_at = retry_at


class Backend(Protocol):
    name: str
    model: str

    def generate(self, request: Request) -> Reply: ...
