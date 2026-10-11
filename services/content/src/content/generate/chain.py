"""Chains: the backends for one tier, tried in order."""

from collections.abc import Callable
from datetime import datetime

from content.config import Settings
from content.generate import Backend, GenerationError, QuotaExceeded, Reply, Request
from content.generate.claude_code import ClaudeCode
from content.generate.gemini import Gemini


def build(spec: str, settings: Settings) -> list[Backend]:
    """``"claude_code:haiku,gemini:gemini-flash-latest"`` -> backends, dropping Claude
    Code when ``use_claude_code`` is off."""
    backends: list[Backend] = []
    for part in filter(None, (p.strip() for p in spec.split(","))):
        name, _, model = part.partition(":")
        if name == "claude_code":
            if settings.use_claude_code:
                backends.append(
                    ClaudeCode(model or "haiku", settings.claude_code_path,
                               settings.generation_timeout_seconds)
                )  # fmt: skip
        elif name == "gemini":
            backends.append(
                Gemini(model or "gemini-flash-latest", settings.gemini_api_key,
                       settings.generation_timeout_seconds)
            )  # fmt: skip
        else:
            raise ValueError(f"unknown backend {name!r} in chain {spec!r}")
    return backends


def run(
    backends: list[Backend],
    request: Request,
    check: Callable[[dict[str, object]], str | None] | None = None,
) -> Reply:
    """The first backend's reply that passes ``check`` (which returns an error message or
    None). A failed check is retried once with the error attached. Quota errors move on;
    when every backend is out, the earliest reset is raised so the job can wait."""
    resets: list[datetime] = []
    last: Exception | None = None
    for backend in backends:
        attempt = request
        for _ in range(2):
            try:
                reply = backend.generate(attempt)
            except QuotaExceeded as error:
                if error.retry_at:
                    resets.append(error.retry_at)
                last = error
                break
            problem = check(reply.data) if check else None
            if problem is None:
                return reply
            last = GenerationError(problem)
            attempt = Request(
                attempt.task,
                attempt.system,
                request.prompt + f"\n\nYour previous reply had a problem: {problem}. Fix it.",
                attempt.schema,
            )
    if resets and isinstance(last, QuotaExceeded):
        raise QuotaExceeded("every backend is out of quota", min(resets))
    raise last or GenerationError("no backends configured")
