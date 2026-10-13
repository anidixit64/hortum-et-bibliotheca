"""Chains: the backends for one tier, tried in order."""

import logging
from collections.abc import Callable
from datetime import datetime

from content.config import Settings
from content.generate import Backend, GenerationError, QuotaExceeded, Reply, Request
from content.generate.claude_code import ClaudeCode
from content.generate.gemini import Gemini
from content.generate.openai_compat import OpenAICompat
from content.trace import event as trace_event

log = logging.getLogger(__name__)

# Groq's free tier rejects a request over 8,000 tokens (Diocletian's article was 16,309).
# Stay under that before the HTTP call; a 413 used to fail the whole section.
GROQ_CHAR_LIMIT = 24_000


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
            # An empty key is not a quota outage. Leaving it in the chain made every
            # writing job defer for an hour, and the topic page waited on that.
            if settings.gemini_api_key:
                backends.append(
                    Gemini(model or "gemini-3.8-flash", settings.gemini_api_key,
                           settings.generation_timeout_seconds)
                )  # fmt: skip
        elif name in OPENAI_PROVIDERS:
            base_url, default_model = OPENAI_PROVIDERS[name]
            key_attr = f"{name}_api_key"
            api_key = getattr(settings, key_attr, "")
            if api_key:
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


def _task_offset(task: str, n: int) -> int:
    """Deterministic offset so parallel tasks start at different providers."""
    return sum(ord(c) for c in task) % n


def order_backends(backends: list[Backend], task: str) -> list[Backend]:
    """Providers in chain order, rotated so concurrent tasks try a different one first.

    Models of one provider stay together: the section tries that provider's models, then
    the next provider. A hashed task name spreads summary, facts, theme, and the rest
    across Gemini, Groq, and Cerebras when all three keys are set.
    """
    groups: dict[str, list[Backend]] = {}
    names: list[str] = []
    for backend in backends:
        if backend.name not in groups:
            names.append(backend.name)
            groups[backend.name] = []
        groups[backend.name].append(backend)
    if len(names) > 1:
        off = _task_offset(task, len(names))
        names = names[off:] + names[:off]
    return [backend for name in names for backend in groups[name]]


def run(
    backends: list[Backend],
    request: Request,
    check: Callable[[dict[str, object]], str | None] | None = None,
) -> Reply:
    """The first backend's reply that passes ``check`` (which returns an error message or
    None). A failed check is retried once with the error attached. Quota errors and any
    other provider error move on to the next model; when every backend is out of quota,
    the earliest reset is raised so the job can wait.
    """
    ordered = order_backends(backends, request.task)
    providers = [f"{backend.name}:{getattr(backend, 'model', '')}" for backend in ordered]
    trace_event(
        "model.input",
        task=request.task,
        providers=providers,
        system=request.system,
        prompt=request.prompt,
    )
    if not ordered:
        trace_event("model.error", task=request.task, error="no backends configured", output=None)
        raise GenerationError("no backends configured")
    resets: list[datetime] = []
    last: Exception | None = None
    for backend in ordered:
        attempt = request
        model = getattr(backend, "model", "")
        prompt_chars = len(attempt.system) + len(attempt.prompt)
        if backend.name == "groq" and prompt_chars > GROQ_CHAR_LIMIT:
            log.info("%s: groq %s skipped, prompt is over the 8k token cap", request.task, model)
            trace_event(
                "model.error", task=request.task, provider="groq", model=model,
                error="prompt over groq token cap", output=None,
            )  # fmt: skip
            last = GenerationError("prompt over groq token cap")
            continue
        for _ in range(2):
            try:
                reply = backend.generate(attempt)
            except QuotaExceeded as error:
                if error.retry_at:
                    resets.append(error.retry_at)
                log.info("%s: %s %s is out (%s), trying the next", request.task, backend.name,
                         model, error)  # fmt: skip
                trace_event(
                    "model.error", task=request.task, provider=backend.name, model=model,
                    error=str(error), output=None,
                )  # fmt: skip
                last = error
                break
            except GenerationError as error:
                log.info("%s: %s %s failed (%s), trying the next", request.task, backend.name,
                         model, error)  # fmt: skip
                trace_event(
                    "model.error", task=request.task, provider=backend.name, model=model,
                    error=str(error), output=None,
                )  # fmt: skip
                last = error
                break
            problem = check(reply.data) if check else None
            if problem is None:
                trace_event(
                    "model.output",
                    task=request.task,
                    provider=reply.backend,
                    model=reply.model,
                    input_tokens=reply.input_tokens,
                    output_tokens=reply.output_tokens,
                    output=reply.data,
                )
                return reply
            log.info("%s: %s reply rejected (%s)", request.task, reply.model, problem)
            trace_event(
                "model.rejected", task=request.task, provider=reply.backend, model=reply.model,
                error=problem, output=reply.data,
            )  # fmt: skip
            last = GenerationError(problem)
            attempt = Request(
                attempt.task,
                attempt.system,
                request.prompt + f"\n\nYour previous reply had a problem: {problem}. Fix it.",
                attempt.schema,
            )
    if resets and isinstance(last, QuotaExceeded):
        last = QuotaExceeded("every backend is out of quota", min(resets))
    error = last or GenerationError("no backends configured")
    trace_event(
        "model.error", task=request.task, error=str(error), providers=providers, output=None
    )
    raise error
