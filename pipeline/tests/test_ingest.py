import sqlite3

from hortum_pipeline import ingest
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import NullReporter


def test_unwrap_extended_json() -> None:
    raw = {"a": {"$numberInt": "8"}, "b": [{"$oid": "x"}], "c": {"$date": {"$numberLong": "5"}}}
    assert ingest.unwrap(raw) == {"a": 8, "b": ["x"], "c": 5}


def test_strip_trailing_author_tags() -> None:
    assert ingest.strip_trailing_tags("Tilted Arc <MS>") == "Tilted Arc"
    assert ingest.strip_trailing_tags("Olympus Mons (1) [AU]") == "Olympus Mons"
    assert ingest.strip_trailing_tags("Charles I") == "Charles I"


def test_ingest_dedupes_and_skips_empty(settings: PipelineSettings) -> None:
    ingest.run(settings, NullReporter())
    conn = sqlite3.connect(settings.corpus_path)
    ids = {r[0] for r in conn.execute("SELECT id FROM tossups")}
    assert ids == {"t1", "t2", "t4", "t5", "t6", "t7"}  # t3 duplicates t2, t8 is empty
    assert conn.execute(
        "SELECT kept_id FROM tossup_duplicates WHERE tossup_id = 't3'"
    ).fetchone() == ("t2",)
    answer = conn.execute("SELECT answer_text, difficulty FROM tossups WHERE id = 't1'").fetchone()
    assert answer == ("Leo Tolstoy [or Lev Nikolayevich Tolstoy]", 3)
