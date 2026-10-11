"""The Gemini backend: the Gemini API's free tier, JSON output.

Free-tier prompts and outputs may be used by Google to improve its products; the inputs
here are Wikipedia text and quiz clues. Daily quotas reset at midnight Pacific time.
"""

import json
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from content.generate import GenerationError, QuotaExceeded, Reply, Request

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


OVERLOADED_RETRIES = (2, 8)  # seconds to wait before trying a busy model again
BUSY_DEFER = timedelta(minutes=5)  # then the job waits this long
MINUTE_LIMIT_DEFER = timedelta(minutes=2)


def rate_limit_until(body: str) -> datetime:
    """When a 429 lifts: Pacific midnight for a daily quota, a couple of minutes for the
    per-minute limits (requests or tokens per minute)."""
    if "PerDay" in body or "per day" in body.lower():
        return next_pacific_midnight()
    return datetime.now(ZoneInfo("UTC")) + MINUTE_LIMIT_DEFER


def next_pacific_midnight() -> datetime:
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    return (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)


class Gemini:
    name = "gemini"

    def __init__(self, model: str, api_key: str, timeout: float = 120.0) -> None:
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def body(self, request: Request) -> dict[str, Any]:
        return {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": request.prompt
                            + "\n\nReply with JSON matching this schema:\n"
                            + json.dumps(request.schema)
                        }
                    ],
                }
            ],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
        }

    def generate(self, request: Request) -> Reply:
        if not self.api_key:
            raise QuotaExceeded("no Gemini API key (CONTENT_GEMINI_API_KEY)")
        for wait in (*OVERLOADED_RETRIES, None):
            try:
                response = httpx.post(
                    API.format(model=self.model),
                    headers={"x-goog-api-key": self.api_key},
                    json=self.body(request),
                    timeout=self.timeout,
                )
            except httpx.HTTPError as error:
                raise GenerationError(f"Gemini request failed: {error}") from error
            if response.status_code not in (500, 503):  # 503: "high demand", usually brief
                break
            if wait is None:
                raise QuotaExceeded(
                    f"Gemini {self.model} is overloaded",
                    datetime.now(ZoneInfo("UTC")) + BUSY_DEFER,
                )
            time.sleep(wait)
        if response.status_code == 429:
            raise QuotaExceeded("Gemini quota or rate limit", rate_limit_until(response.text))
        if response.status_code >= 400:
            raise GenerationError(f"Gemini {response.status_code}: {response.text[:300]}")
        payload = response.json()
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as error:
            raise GenerationError(f"unusable Gemini reply: {str(payload)[:300]}") from error
        if not isinstance(data, dict):
            raise GenerationError("Gemini reply is not a JSON object")
        usage = payload.get("usageMetadata", {})
        return Reply(
            data=data,
            backend=self.name,
            model=self.model,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
        )
