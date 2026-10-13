import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from content import cleanup
from content.config import Settings
from content.generate import GenerationError, QuotaExceeded, Reply, Request, chain


def found() -> dict[str, Any]:
    return {
        "name": "Gore Vidal",
        "category": "Literature",
        "fingerprint": "f",
        "candidates": [
            {"id": 1, "rank": 1, "label": "Pillar", "n_questions": 3,
             "spellings": {"Pillar": ["a", "b", "c"]},
             "sentences": ["His novel The City and the Pillar shocked readers."]},
            {"id": 2, "rank": 2, "label": "Willy Wonka", "n_questions": 3,
             "spellings": {"Willy Wonka": ["d", "e"], "Willy": ["f"]},
             "sentences": ["Willy Wonka runs a factory.", "Willy dies in the poem."]},
            {"id": 3, "rank": 3, "label": "TV appearance", "n_questions": 2,
             "spellings": {"TV appearance": ["a", "g"]}, "sentences": ["In a TV appearance..."]},
            {"id": 4, "rank": 4, "label": "Buckley", "n_questions": 1,
             "spellings": {"Buckley": ["h"]}, "sentences": ["He debated William F. Buckley."]},
            {"id": 5, "rank": 5, "label": "William F. Buckley", "n_questions": 2,
             "spellings": {"William F. Buckley": ["h", "i"]}, "sentences": ["Buckley..."]},
        ],
    }  # fmt: skip


def test_edits_are_checked_and_counts_recomputed() -> None:
    data = {
        "edits": [
            {"id": 1, "action": "rename", "label": "The City and the Pillar"},
            {"id": 2, "action": "keep", "remove_spellings": ["Willy"]},
            {"id": 3, "action": "drop", "reason": "generic"},
            {"id": 4, "action": "merge", "into": 5},
            {"id": 5, "action": "rename", "label": "Gore Vidal's nemesis"},  # invented words
        ]
    }
    checked = cleanup.check(found(), data, {})
    assert checked.renames == {1: "The City and the Pillar"}
    assert any("not in its sentences" in r for r in checked.rejected)
    cleaned = cleanup.apply(found(), checked)
    assert [(c["label"], c["n_questions"], c["clue_ids"]) for c in cleaned] == [
        ("The City and the Pillar", 3, [1]),
        ("Willy Wonka", 2, [2]),  # the other Willy's question is gone
        ("William F. Buckley", 2, [5, 4]),  # h counted once
    ]


def test_merges_into_dropped_targets_are_undone_and_cycles_broken() -> None:
    data = {
        "edits": [
            {"id": 1, "action": "merge", "into": 3},
            {"id": 3, "action": "drop"},
            {"id": 4, "action": "merge", "into": 5},
            {"id": 5, "action": "merge", "into": 4},
        ]
    }
    checked = cleanup.check(found(), data, {})
    # Into a dropped clue: undone. Two clues merging into each other: one direction kept.
    assert checked.merges == {5: 4}
    assert len(checked.rejected) == 2


def test_a_reply_missing_most_candidates_is_asked_again() -> None:
    assert cleanup.problem(found(), {"edits": [{"id": 1, "action": "keep"}]}) is not None
    edits = [{"id": i, "action": "keep"} for i in range(1, 6)]
    assert cleanup.problem(found(), {"edits": edits}) is None


def test_ner_hints() -> None:
    ents = [[["The City and the Pillar", "WORK_OF_ART"], ["Gore Vidal", "PERSON"]],
            [["The City and the Pillar", "WORK_OF_ART"]]]  # fmt: skip
    assert cleanup.ner_hint("Pillar", ents) == "The City and the Pillar"
    assert cleanup.ner_hint("Newfoundland dog Seaman", [[["Seaman", "PERSON"]]]) == "Seaman"
    assert cleanup.ner_hint("Gore Vidal", ents) is None


class Fake:
    def __init__(self, name: str, replies: list[Any]) -> None:
        self.name, self.model, self.replies = name, "m", replies

    def generate(self, request: Request) -> Reply:
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Reply(reply, self.name, "m")


def test_chain_falls_back_on_quota_and_retries_a_bad_reply_once() -> None:
    request = Request("t", "s", "p", {})
    later = datetime.now(UTC) + timedelta(hours=2)
    first = Fake("claude_code", [QuotaExceeded("limit", later)])
    second = Fake("gemini", [{"bad": True}, {"ok": True}])
    reply = chain.run([first, second], request, lambda d: None if d.get("ok") else "not ok")
    assert reply.backend == "gemini" and reply.data == {"ok": True}

    with pytest.raises(QuotaExceeded) as waited:
        chain.run([Fake("a", [QuotaExceeded("x", later)])], request)
    assert waited.value.retry_at == later
    with pytest.raises(GenerationError):
        chain.run([Fake("a", [{"bad": 1}, {"bad": 2}])], request, lambda d: "still bad")


def test_turning_claude_code_off_leaves_gemini() -> None:
    on = Settings(_env_file=None, use_claude_code=True, gemini_api_key="k")  # type: ignore[call-arg]
    off = Settings(_env_file=None, use_claude_code=False, gemini_api_key="k")  # type: ignore[call-arg]
    spec = "claude_code:haiku,gemini:gemini-flash-latest"
    assert [b.name for b in chain.build(spec, on)] == ["claude_code", "gemini"]
    assert [b.name for b in chain.build(spec, off)] == ["gemini"]


def test_a_long_prompt_skips_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "order_backends", lambda backends, task: backends)
    request = Request("facts", "system", "x" * (chain.GROQ_CHAR_LIMIT + 1), {})
    blocked = GenerationError("should not be called")
    groq = Fake("groq", [blocked])
    gemini = Fake("gemini", [{"ok": True}])
    reply = chain.run([groq, gemini], request)
    assert reply.backend == "gemini"
    assert groq.replies == [blocked]


def test_a_short_prompt_still_uses_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chain, "order_backends", lambda backends, task: backends)
    request = Request("theme", "system", "a tinted background", {})
    groq = Fake("groq", [{"ok": True}])
    gemini = Fake("gemini", [GenerationError("should not be called")])
    reply = chain.run([groq, gemini], request)
    assert reply.backend == "groq"
    assert gemini.replies


def test_a_provider_error_tries_the_next_provider() -> None:
    request = Request("summary", "s", "p", {})
    first = Fake("cerebras", [GenerationError("cerebras 400: unknown model")])
    second = Fake("gemini", [{"ok": True}])
    reply = chain.run([first, second], request)
    assert reply.backend == "gemini" and reply.data == {"ok": True}


def test_parallel_tasks_start_on_different_providers() -> None:
    cerebras, groq, gemini = Fake("cerebras", []), Fake("groq", []), Fake("gemini", [])
    backends = [cerebras, groq, gemini]
    tasks = ("clues", "facts", "summary")
    firsts = {chain.order_backends(backends, task)[0].name for task in tasks}
    assert firsts == {"cerebras", "groq", "gemini"}


def test_a_missing_key_records_the_prompt_and_no_output(tmp_path: Path) -> None:
    from content import trace

    trace.configure(tmp_path / "trace.jsonl")
    request = Request("summary", "system text", "prompt text", {})
    with pytest.raises(GenerationError, match="no backends configured"):
        chain.run([], request)
    lines = (tmp_path / "trace.jsonl").read_text().splitlines()
    stages = [json.loads(line)["stage"] for line in lines]
    assert stages == ["model.input", "model.error"]
    recorded = json.loads(lines[0])
    assert recorded["prompt"] == "prompt text" and recorded["system"] == "system text"
    assert json.loads(lines[1])["output"] is None


def test_providers_without_keys_are_not_backends() -> None:
    settings = Settings(_env_file=None, use_claude_code=False)  # type: ignore[call-arg]
    spec = "claude_code:haiku,gemini:gemini-flash-latest,groq:llama"
    assert chain.build(spec, settings) == []
    with pytest.raises(GenerationError, match="no backends configured"):
        chain.run([], Request("t", "s", "p", {}))


def test_renames_may_correct_a_misspelling_but_not_invent_words() -> None:
    source = cleanup.words("Vincente de Valverde gave him a breviary; a Stetter reation")
    assert cleanup.known_word("vicente", source)
    assert cleanup.known_word("reaction", source)
    assert not cleanup.known_word("pizarro", source)


def groups_found() -> dict[str, Any]:
    def group(gid: int, answer: str, category: str, n: int) -> dict[str, Any]:
        return {"id": gid, "key": answer.lower(), "category": category, "answer": answer,
                "tossups": [f"{gid}-{i}" for i in range(n)], "example": ""}  # fmt: skip

    return {
        "name": "Vienna Secession",
        "category": "Fine Arts",
        "candidates": [],
        "groups": [
            group(1, "Vienna", "Fine Arts", 13),
            group(2, "Vienna Secession", "Fine Arts", 3),
        ],
    }


def test_an_off_topic_group_may_be_the_largest_while_the_named_one_remains() -> None:
    chosen, notes = cleanup.off_topic(groups_found(), [1])
    assert [g["id"] for g in chosen] == [1] and notes == []
    chosen, notes = cleanup.off_topic(groups_found(), [2])
    assert chosen == [] and "names the topic" in notes[0]


def test_a_same_named_group_in_another_subject_may_go() -> None:
    found = groups_found()
    found["name"], found["category"] = "Translation", "Social Science"
    found["groups"][0]["answer"], found["groups"][0]["category"] = "translation", "Science"
    found["groups"][1]["answer"], found["groups"][1]["category"] = "translation", "Social Science"
    chosen, _ = cleanup.off_topic(found, [1, 2])
    assert [g["id"] for g in chosen] == [1]


def test_without_a_named_group_left_at_most_half_goes() -> None:
    found = groups_found()
    found["groups"][1]["answer"] = "Klimt"
    chosen, notes = cleanup.off_topic(found, [1])
    assert chosen == [] and "under half" in notes[0]


def test_export_overrides_merges_with_hand_written_entries(tmp_path: Any) -> None:
    import json
    import sqlite3

    from content import db
    from content.cli import export_overrides

    conn: sqlite3.Connection = db.connect(tmp_path / "content.db")
    payload = {
        "excluded_groups": [
            {"id": 7, "key": "rings", "category": "History", "answer": "rings", "tossups": ["t1"]}
        ]
    }
    conn.execute(
        "INSERT INTO generations VALUES ('Q15228', 'clues', 'f', 3, 'claude_code', 'haiku', "
        "?, 1, 1, '2026-10-11T00:00:00')",
        (json.dumps(payload),),
    )
    path = tmp_path / "links.jsonl"
    path.write_text(json.dumps({"key": "vienna", "category": "Fine Arts", "topic": "Q208208",
                                "action": "unlink", "source": "hand"}) + "\n")  # fmt: skip
    assert export_overrides(conn, path) == (1, 2)
    assert export_overrides(conn, path) == (0, 2)  # idempotent
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    assert {(e["key"], e["source"]) for e in entries} == {
        ("rings", "cleanup:haiku"),
        ("vienna", "hand"),
    }
