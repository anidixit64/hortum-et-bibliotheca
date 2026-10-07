import sqlite3

import pytest

from hortum_pipeline import answer_stage, grouping, ingest
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import NullReporter
from hortum_pipeline.verify import run_checks


@pytest.fixture
def built(settings: PipelineSettings) -> PipelineSettings:
    for stage in (ingest, answer_stage, grouping):
        stage.run(settings, NullReporter())
    return settings


def by_name(settings: PipelineSettings, stage: str) -> dict[str, bool]:
    return {c.name: c.passed for c in run_checks(settings, [stage])}


def test_clean_build_passes_ingest_and_group_checks(built: PipelineSettings) -> None:
    assert all(by_name(built, "ingest").values())
    assert all(by_name(built, "group").values())


def test_missing_stage_is_reported(built: PipelineSettings) -> None:
    assert by_name(built, "link") == {"stage output present": False}


def test_unapplied_fix_fails_parse_check(built: PipelineSettings) -> None:
    from hortum_pipeline.overrides import AnswerOverride, OverrideStore

    conn = sqlite3.connect(built.corpus_path)
    key = conn.execute("SELECT line_key FROM answer_parses WHERE tossup_id='t7'").fetchone()[0]
    OverrideStore(built.answer_overrides_path).save(AnswerOverride(key, "x", "entropy"))
    assert by_name(built, "parse-answers")["every hand fix is applied"] is False


def test_tampered_data_fails_ingest_check(built: PipelineSettings) -> None:
    conn = sqlite3.connect(built.corpus_path)
    conn.execute("UPDATE tossups SET set_id = 'nope' WHERE id = 't1'")
    conn.commit()
    assert by_name(built, "ingest")["every question belongs to a known set"] is False
