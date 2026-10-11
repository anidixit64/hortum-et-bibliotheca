"""The Gemini backend: the Gemini API's free tier, JSON output.

Free-tier prompts and outputs may be used by Google to improve its products; the inputs
here are Wikipedia text and quiz clues. Daily quotas reset at midnight Pacific time.
"""

import json
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from content.generate import GenerationError, QuotaExceeded, Reply, Request

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


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
        try:
            response = httpx.post(
                API.format(model=self.model),
                headers={"x-goog-api-key": self.api_key},
                json=self.body(request),
                timeout=self.timeout,
            )
        except httpx.HTTPError as error:
            raise GenerationError(f"Gemini request failed: {error}") from error
        if response.status_code == 429:
            raise QuotaExceeded("Gemini quota or rate limit", next_pacific_midnight())
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
