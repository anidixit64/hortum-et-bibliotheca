"""The tracer questions, followed through every stage that runs offline.

Expectations live in pipeline/eval/tracers.yaml and are the same ones `verify` asserts on
the real corpus; this rebuilds a two-question corpus from their raw records.
"""

import shutil
from pathlib import Path

import pytest

from hortum_pipeline import answer_stage, clues, grouping, ingest
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import NullReporter
from hortum_pipeline.verify import run_checks

EVAL = Path(__file__).parents[1] / "eval"
OFFLINE_STAGES = ["ingest", "parse-answers", "group", "clues"]


@pytest.fixture(scope="module")
def tracer_corpus(tmp_path_factory: pytest.TempPathFactory) -> PipelineSettings:
    root = tmp_path_factory.mktemp("tracers")
    (root / "data" / "raw").mkdir(parents=True)
    shutil.copy(EVAL / "tracer_records.ndjson", root / "data" / "raw" / "tossups.json")
    (root / "eval").mkdir()
    shutil.copy(EVAL / "tracers.yaml", root / "eval" / "tracers.yaml")
    settings = PipelineSettings(  # type: ignore[call-arg]
        _env_file=None, data_dir=root / "data", overrides_dir=root / "overrides"
    )
    for stage in (ingest, answer_stage, grouping, clues):
        stage.run(settings, NullReporter())
    return settings


@pytest.mark.parametrize("stage", OFFLINE_STAGES)
def test_tracers_match_expectations(tracer_corpus: PipelineSettings, stage: str) -> None:
    results = [c for c in run_checks(tracer_corpus, [stage]) if c.name.startswith("tracer")]
    assert len(results) == 2, "both tracers should have expectations for this stage"
    for check in results:
        assert check.passed, f"{check.name}: {check.detail}"


def test_stage_checks_pass_on_the_tracer_corpus(tracer_corpus: PipelineSettings) -> None:
    failed = [c for c in run_checks(tracer_corpus, OFFLINE_STAGES) if not c.passed]
    assert not failed, [(c.name, c.detail) for c in failed]
