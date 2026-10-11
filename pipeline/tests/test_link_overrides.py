import json
from pathlib import Path

from hortum_pipeline import topics


def test_load_unlinks_reads_only_unlink_entries(tmp_path: Path) -> None:
    path = tmp_path / "links.jsonl"
    path.write_text(
        json.dumps({"key": "rings", "category": "History", "topic": "Q15228", "action": "unlink"})
        + "\n\n"
        + json.dumps({"key": "x", "category": "", "topic": "Q1", "action": "something else"})
        + "\n"
    )
    assert topics.load_unlinks(path) == {("rings", "History", "Q15228")}
    assert topics.load_unlinks(tmp_path / "missing.jsonl") == set()
