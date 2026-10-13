"""A stage log for content jobs: what was loaded, what was sent, what came back.

One JSON object per line in ``data/generation-trace.jsonl``. The worker log gets a short
line for the same event. API keys are never written.
"""

import json
import logging
import threading
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("content.trace")

_path: Path | None = None
_lock = threading.Lock()
_topic: ContextVar[str] = ContextVar("trace_topic", default="")
_kind: ContextVar[str] = ContextVar("trace_kind", default="")


def configure(path: Path) -> None:
    """Append events to ``path``. Creates the parent directory."""
    global _path
    path.parent.mkdir(parents=True, exist_ok=True)
    _path = path
    log.info("trace file %s", path)


def bind(topic_id: str, kind: str) -> tuple[Any, Any]:
    """Remember which job the model calls in this thread belong to."""
    return _topic.set(topic_id), _kind.set(kind)


def reset(tokens: tuple[Any, Any]) -> None:
    _topic.reset(tokens[0])
    _kind.reset(tokens[1])


def event(stage: str, **fields: Any) -> None:
    """Record one stage. ``prompt``, ``system``, ``output``, and ``loaded`` are stored whole."""
    record: dict[str, Any] = {
        "at": datetime.now(UTC).isoformat(),
        "stage": stage,
        "topic_id": fields.pop("topic_id", None) or _topic.get(),
        "kind": fields.pop("kind", None) or _kind.get(),
    }
    record.update(fields)
    log.info("%s %s", stage, _summary(record))
    if _path is None:
        return
    line = json.dumps(record, ensure_ascii=False, default=str)
    try:
        with _lock, _path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        log.warning("could not append %s", _path, exc_info=True)


def _summary(record: dict[str, Any]) -> str:
    names = ("topic_id", "kind", "task", "provider", "model", "error")
    bits = [f"{key}={record[key]}" for key in names if record.get(key)]
    for key in ("prompt", "system", "output", "loaded"):
        value = record.get(key)
        if value is None:
            continue
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        bits.append(f"{key}_chars={len(text)}")
    return " ".join(bits)
