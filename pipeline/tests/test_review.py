import json
import sqlite3

from hortum_pipeline import answer_stage, ingest
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import NullReporter
from hortum_pipeline.review import ReviewModel


def build(settings: PipelineSettings) -> ReviewModel:
    ingest.run(settings, NullReporter())
    answer_stage.run(settings, NullReporter())
    return ReviewModel(settings.corpus_path, settings.answer_overrides_path)


def test_lists_only_low_confidence_lines(settings: PipelineSettings) -> None:
    model = build(settings)
    items = model.items(threshold=0.8)
    assert [i.guess for i in items] == ["temperature AND entropy"]
    assert model.counts(0.8)["questions"] == 1


def test_save_rerun_and_undo(settings: PipelineSettings) -> None:
    model = build(settings)
    item = model.items(0.8)[0]

    model.save(item, "entropy")
    saved = [json.loads(line) for line in settings.answer_overrides_path.read_text().splitlines()]
    assert saved[0]["main"] == "entropy"
    assert len(model.pending()) == 1
    assert model.items(0.8) == []  # fixed lines are hidden unless asked for

    assert model.rerun_pending() == 1
    assert model.pending() == []
    conn = sqlite3.connect(settings.corpus_path)
    row = conn.execute("SELECT main, source, confidence FROM answer_parses WHERE tossup_id='t7'")
    assert row.fetchone() == ("entropy", "override", 1.0)

    model.undo(item.line_key)
    row = conn.execute("SELECT main, source FROM answer_parses WHERE tossup_id='t7'").fetchone()
    assert row == ("temperature AND entropy", "parser")


def test_fixes_survive_a_full_reparse(settings: PipelineSettings) -> None:
    model = build(settings)
    model.save(model.items(0.8)[0], "entropy", exclude=True)
    answer_stage.run(settings, NullReporter())  # as after rebuilding corpus.db
    conn = sqlite3.connect(settings.corpus_path)
    row = conn.execute("SELECT source FROM answer_parses WHERE tossup_id='t7'").fetchone()
    assert row == ("excluded",)


def test_suggestions_rank_similar_confident_answers(settings: PipelineSettings) -> None:
    model = build(settings)
    names = [s.name for s in model.suggestions("Tolstoi")]
    assert names[0] == "Leo Tolstoy"


def test_giveaways_return_last_sentence(settings: PipelineSettings) -> None:
    model = build(settings)
    key = model.items(0.8)[0].line_key
    assert model.giveaways(key) == ["For 10 points, name it."]
