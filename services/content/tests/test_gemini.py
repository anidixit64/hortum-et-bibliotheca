from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from content.generate import QuotaExceeded, Request, gemini

REQUEST = Request("t", "system", "prompt", {"type": "object"})
OK = {
    "candidates": [{"content": {"parts": [{"text": '{"a": 1}'}]}}],
    "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
}


def replies(monkeypatch: pytest.MonkeyPatch, *responses: httpx.Response) -> list[int]:
    queue, calls = list(responses), []

    def post(*args: Any, **kwargs: Any) -> httpx.Response:
        calls.append(1)
        return queue.pop(0)

    monkeypatch.setattr(gemini.httpx, "post", post)
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    return calls


def test_a_busy_model_is_retried_then_the_job_waits_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = gemini.Gemini("gemini-3.8-flash", "key", 30)
    replies(monkeypatch, httpx.Response(503, json={}), httpx.Response(200, json=OK))
    assert backend.generate(REQUEST).data == {"a": 1}
    calls = replies(monkeypatch, *[httpx.Response(503, json={})] * 3)
    with pytest.raises(QuotaExceeded) as busy:
        backend.generate(REQUEST)
    assert len(calls) == 3
    assert busy.value.retry_at is not None
    assert busy.value.retry_at - datetime.now(UTC) < timedelta(minutes=10)


def test_per_minute_limits_wait_minutes_and_daily_quotas_wait_for_midnight() -> None:
    soon = gemini.rate_limit_until("Quota exceeded for metric: ...requests_per_model_per_minute")
    assert soon - datetime.now(UTC) < timedelta(minutes=5)
    later = gemini.rate_limit_until("Quota exceeded: GenerateRequestsPerDayPerProjectPerModel")
    assert later == gemini.next_pacific_midnight()


def test_the_json_is_found_after_gemma_reasoning() -> None:
    assert gemini.reply_json([{"text": '{"a": 1}'}]) == {"a": 1}
    assert gemini.reply_json([{"text": "plan", "thought": True}, {"text": '{"a": 2}'}]) == {"a": 2}
    reasoning = '*   Goal: facts {like this}\n\n```json\n{"a": 3}\n```'
    assert gemini.reply_json([{"text": reasoning}]) == {"a": 3}
    assert gemini.reply_json([{"text": 'Thinking about it.\n{"a": 4}'}]) == {"a": 4}
    with pytest.raises(ValueError):
        gemini.reply_json([{"text": "no json here"}])
