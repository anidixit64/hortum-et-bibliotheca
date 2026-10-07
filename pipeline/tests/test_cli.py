from pathlib import Path

import pytest

from hortum_pipeline import stages
from hortum_pipeline.cli import EXIT_NOT_IMPLEMENTED, build_parser, main
from hortum_pipeline.stages import STAGES, Stage


@pytest.fixture(autouse=True)
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI tests must never touch the real data/ directory."""
    monkeypatch.setenv("PIPELINE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PIPELINE_OVERRIDES_DIR", str(tmp_path / "overrides"))


@pytest.fixture
def unimplemented(monkeypatch: pytest.MonkeyPatch) -> str:
    stage = Stage("snapshot", "not built yet", phase=99)
    monkeypatch.setitem(stages.STAGES_BY_NAME, "snapshot", stage)
    monkeypatch.setattr("hortum_pipeline.cli.STAGES", (*STAGES[:-1], stage))
    return "snapshot"


def test_help_lists_every_stage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--help"])
    out = capsys.readouterr().out
    for stage in STAGES:
        assert stage.name in out
    assert "review-answers" in out


def test_stage_order_matches_architecture_doc() -> None:
    assert [s.name for s in STAGES] == [
        "ingest", "parse-answers", "group", "link", "facts",
        "clues", "cluster", "score", "relate", "confuse", "snapshot",
    ]  # fmt: skip


def test_unimplemented_stage_reports_and_fails(
    unimplemented: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([unimplemented]) == EXIT_NOT_IMPLEMENTED
    assert "not implemented yet" in capsys.readouterr().err


def test_all_from_an_unimplemented_stage_fails(unimplemented: str) -> None:
    assert main(["all", "--from", unimplemented]) == EXIT_NOT_IMPLEMENTED


def test_all_stops_cleanly_before_unbuilt_stages(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[str] = []
    built = Stage("one", "built", 1, lambda s, r: ran.append("one"))
    later = Stage("two", "not built", 2)
    monkeypatch.setattr("hortum_pipeline.cli.STAGES", (built, later))
    monkeypatch.setitem(stages.STAGES_BY_NAME, "one", built)
    assert main(["all"]) == 0
    assert ran == ["one"]
    assert "stopped before 'two'" in capsys.readouterr().err


def test_missing_raw_dump_fails_clearly() -> None:
    with pytest.raises(FileNotFoundError, match="raw dump not found"):
        main(["ingest"])
