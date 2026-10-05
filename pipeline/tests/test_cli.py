import pytest

from hortum_pipeline.cli import EXIT_NOT_IMPLEMENTED, build_parser, main
from hortum_pipeline.stages import STAGES


def test_help_lists_every_stage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--help"])
    out = capsys.readouterr().out
    for stage in STAGES:
        assert stage.name in out


def test_stage_order_matches_architecture_doc() -> None:
    assert [s.name for s in STAGES] == [
        "ingest", "parse-answers", "group", "link", "facts",
        "clues", "cluster", "score", "relate", "confuse", "snapshot",
    ]  # fmt: skip


def test_unimplemented_stage_reports_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ingest"]) == EXIT_NOT_IMPLEMENTED
    assert "not implemented yet" in capsys.readouterr().err


def test_all_stops_at_first_unimplemented_stage() -> None:
    assert main(["all", "--from", "clues"]) == EXIT_NOT_IMPLEMENTED
