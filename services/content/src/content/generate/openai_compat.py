"""OpenAI-compatible backend: works with Groq, Cerebras, NVIDIA NIM, OpenRouter, Mistral,
GitHub Models, and any other provider that speaks the OpenAI chat-completions API.

Free tiers have per-minute and per-day rate limits. A 429 defers the job; a 5xx retries
briefly then defers. Each provider's daily quota resets at its own midnight (UTC for most).
"""

import json
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from content.generate import GenerationError, QuotaExceeded, Reply, Request

OVERLOADED_RETRIES = (2, 8)  # seconds between retries on 5xx
BUSY_DEFER = timedelta(minutes=5)
RATE_LIMIT_DEFER = timedelta(minutes=2)
DAILY_DEFER_HOURS = 6  # wait this many hours when a daily limit is hit


class OpenAICompat:
    """A backend for any provider with an OpenAI-compatible /chat/completions endpoint."""

    name = "openai_compat"

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        timeout: float = 120.0,
        provider: str = "openai_compat",
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.provider = provider
        self.name = provider  # for logging: "groq", "cerebras", etc.

    def generate(self, request: Request) -> Reply:
        if not self.api_key:
            raise QuotaExceeded(f"no API key for {self.provider}")
        url = f"{self.base_url}/chat/completions"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {
                    "role": "user",
                    "content": request.prompt
                    + "\n\nReply with JSON matching this schema:\n"
                    + json.dumps(request.schema),
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        for wait in (*OVERLOADED_RETRIES, None):
            try:
                response = httpx.post(url, headers=headers, json=body, timeout=self.timeout)
            except httpx.HTTPError as error:
                raise GenerationError(f"{self.provider} request failed: {error}") from error
            if response.status_code not in (500, 502, 503):
                break
            if wait is None:
                raise QuotaExceeded(
                    f"{self.provider} {self.model} is overloaded",
                    datetime.now(ZoneInfo("UTC")) + BUSY_DEFER,
                )
            time.sleep(wait)
        if response.status_code == 429:
            # Check if it's a daily or per-minute limit.
            text = response.text.lower()
            if "per day" in text or "daily" in text:
                retry_at = datetime.now(ZoneInfo("UTC")) + timedelta(hours=DAILY_DEFER_HOURS)
            else:
                retry_at = datetime.now(ZoneInfo("UTC")) + RATE_LIMIT_DEFER
            raise QuotaExceeded(f"{self.provider} rate limit", retry_at)
        if response.status_code >= 400:
            raise GenerationError(f"{self.provider} {response.status_code}: {response.text[:300]}")
        payload = response.json()
        try:
            text = payload["choices"][0]["message"]["content"]
            data = json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError, ValueError) as error:
            # Some models wrap JSON in markdown fences or add reasoning text.
            raw_text = str(payload.get("choices", [{}])[0].get("message", {}).get("content", ""))
            data = _extract_json(raw_text)
            if data is None:
                raise GenerationError(
                    f"unusable {self.provider} reply: {raw_text[:300]}"
                ) from error
        if not isinstance(data, dict):
            raise GenerationError(f"{self.provider} reply is not a JSON object")
        usage = payload.get("usage", {})
        return Reply(
            data=data,
            backend=self.name,
            model=self.model,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )


def _extract_json(text: str) -> dict[str, Any] | None:
    """Try to find a JSON object in text that may have markdown fences or reasoning."""
    import re

    # Try fenced code blocks first.
    for match in reversed(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)):
        try:
            return json.loads(match)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            continue
    # Try the last JSON object in the text.
    start = text.rfind("\n{")
    start = start + 1 if start >= 0 else text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start : end + 1])  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass
    return None
