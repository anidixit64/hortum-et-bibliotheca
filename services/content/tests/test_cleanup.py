from datetime import UTC, datetime, timedelta
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
    on = Settings(_env_file=None, use_claude_code=True)  # type: ignore[call-arg]
    off = Settings(_env_file=None, use_claude_code=False)  # type: ignore[call-arg]
    spec = "claude_code:haiku,gemini:gemini-flash-latest"
    assert [b.name for b in chain.build(spec, on)] == ["claude_code", "gemini"]
    assert [b.name for b in chain.build(spec, off)] == ["gemini"]


def test_renames_may_correct_a_misspelling_but_not_invent_words() -> None:
    source = cleanup.words("Vincente de Valverde gave him a breviary; a Stetter reation")
    assert cleanup.known_word("vicente", source)
    assert cleanup.known_word("reaction", source)
    assert not cleanup.known_word("pizarro", source)
