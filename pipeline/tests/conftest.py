import json
from pathlib import Path
from typing import Any

import pytest

from hortum_pipeline.config import PipelineSettings


def record(oid: str, question: str, answer_html: str, **extra: Any) -> dict[str, Any]:
    """A tossup in the dump's MongoDB extended-JSON format."""
    answer_text = extra.pop(
        "answer_text",
        answer_html.replace("<b>", "").replace("</b>", "").replace("<u>", "").replace("</u>", ""),
    )
    rec: dict[str, Any] = {
        "_id": {"$oid": oid},
        "question": question,
        "question_sanitized": question,
        "answer": answer_html,
        "answer_sanitized": answer_text,
        "category": extra.pop("category", "Literature"),
        "subcategory": extra.pop("subcategory", "American Literature"),
        "difficulty": {"$numberInt": str(extra.pop("difficulty", 3))},
        "number": {"$numberInt": "1"},
        "packet": {"_id": {"$oid": "p1"}, "name": "1", "number": {"$numberInt": "1"}},
        "set": {
            "_id": {"$oid": extra.pop("set_id", "s1")},
            "name": "Test Set",
            "year": {"$numberInt": "2020"},
            "standard": True,
        },
    }
    rec.update(extra)
    return rec


SAMPLE = [
    record(
        "t1",
        "This man wrote War and Peace. For 10 points, name this Russian author.",
        "Leo <b><u>Tolstoy</u></b> [or Lev Nikolayevich <b><u>Tolstoy</u></b>] <AP>",
    ),
    record(
        "t2",
        "This sport is played in the World Cup. For 10 points, name this sport.",
        "<b><u>soccer</u></b> [or association <b><u>football</u></b>; accept futbol]",
        category="Pop Culture",
        set_id="s2",
    ),
    # Same question text as t2 with different punctuation: a duplicate.
    record(
        "t3",
        "This sport is played in the World Cup!  For 10 points, name this sport",
        "<b><u>soccer</u></b>",
        category="Pop Culture",
        set_id="s3",
    ),
    record(
        "t4",
        "This planet is closest to the Sun. For 10 points, name this planet.",
        "<b><u>Mercury</u></b>",
        category="Science",
        subcategory="Astronomy",
    ),
    record(
        "t5",
        "This messenger god has winged sandals. For 10 points, name this god.",
        "<b><u>Mercury</u></b> [or <b><u>Hermes</u></b>]",
        category="Mythology",
    ),
    record(
        "t6",
        "These people treat the sick. For 10 points, name this profession.",
        "<b><u>doctor</u></b>s [or <b><u>physician</u></b>s]",
    ),
    record(
        "t7",
        "Some question with an odd answer line. For 10 points, name it.",
        "<b><u>temperature</u></b> [or <b><u>T</u></b>] AND <b><u>entropy</u></b>",
        category="Science",
    ),
    record("t8", "Empty answer question.", "", answer_text=""),
]


@pytest.fixture
def settings(tmp_path: Path) -> PipelineSettings:
    data = tmp_path / "data"
    (data / "raw").mkdir(parents=True)
    with (data / "raw" / "tossups.json").open("w") as f:
        for rec in SAMPLE:
            f.write(json.dumps(rec) + "\n")
    return PipelineSettings(data_dir=data, overrides_dir=tmp_path / "overrides")
