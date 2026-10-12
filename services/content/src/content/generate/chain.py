"""Chains: the backends for one tier, tried in order."""

import logging
from collections.abc import Callable
from datetime import datetime

from content.config import Settings
from content.generate import Backend, GenerationError, QuotaExceeded, Reply, Request
from content.generate.claude_code import ClaudeCode
from content.generate.gemini import Gemini
from content.generate.openai_compat import OpenAICompat

log = logging.getLogger(__name__)


# OpenAI-compatible providers: name → (base_url, default_model, settings_key_for_api_key).
OPENAI_PROVIDERS: dict[str, tuple[str, str]] = {
    # Groq free tier: 8K TPM, 200K TPD — only usable for short prompts (theme, cleanup).
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-20b"),
    # Cerebras: $5 free credit; qwen-3.8-27b has 450 RPM, 150K tokens/min — very generous.
    "cerebras": ("https://api.cerebras.ai/v1", "qwen-3.8-27b"),
    # SambaNova: $5 free credit, 90 days.
    "sambanova": ("https://api.sambanova.ai/v1", "DeepSeek-V3.1"),
    "openrouter": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "meta/llama-3.3-70b-instruct"),
    "github": ("https://models.inference.ai.azure.com", "gpt-4o"),
    "mistral": ("https://api.mistral.ai/v1", "mistral-large-latest"),
}


def build(spec: str, settings: Settings) -> list[Backend]:
    """``"claude_code:haiku,gemini:gemini-3.8-flash,groq:llama-3.3-70b-versatile"``
    -> backends, dropping Claude Code when ``use_claude_code`` is off and skipping
    providers with no API key."""
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
                Gemini(model or "gemini-3.8-flash", settings.gemini_api_key,
                       settings.generation_timeout_seconds)
            )  # fmt: skip
        elif name in OPENAI_PROVIDERS:
            base_url, default_model = OPENAI_PROVIDERS[name]
            key_attr = f"{name}_api_key"
            api_key = getattr(settings, key_attr, "")
            backends.append(
                OpenAICompat(
                    model=model or default_model,
                    api_key=api_key,
                    base_url=base_url,
                    timeout=settings.generation_timeout_seconds,
                    provider=name,
                )
            )
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
                log.info("%s: %s %s is out (%s), trying the next", request.task, backend.name,
                         getattr(backend, "model", ""), error)  # fmt: skip
                last = error
                break
            problem = check(reply.data) if check else None
            if problem is None:
                return reply
            log.info("%s: %s reply rejected (%s)", request.task, reply.model, problem)
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
