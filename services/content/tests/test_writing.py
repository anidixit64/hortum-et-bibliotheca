from content import writing


def test_summary_checks_marks_length_and_hook() -> None:
    body = "[[1|Ras the Exhorter]] and [[2|the battle royal]] " + " ".join(["w"] * 600)
    good = {"hook": "A man underground burns 1,369 light bulbs. Why?", "summary": body}
    assert writing.summary_problem(good, [1, 2, 3]) is None
    assert "aren't in the list" in str(writing.summary_problem(good, [1]))
    assert "words" in str(writing.summary_problem({**good, "summary": "too short"}, [1, 2]))
    assert "hook" in str(writing.summary_problem({**good, "hook": "Hi."}, [1, 2]))


def test_clean_summary_unmarks_unknown_and_repeated() -> None:
    text, marked = writing.clean_summary("[[1|Ras]] met [[9|Jack]] and [[1|Ras again]].", [1, 2])
    assert text == "[[1|Ras]] met Jack and Ras again." and marked == [1]


def test_explanations_need_every_clue_at_length() -> None:
    entry = {"one_line": "One line.", "explanation": " ".join(["w"] * 230)}
    good = {"explanations": [{"rank": 1, **entry}, {"rank": 2, **entry}]}
    assert writing.explain_problem(good, [1, 2]) is None
    assert "missing" in str(writing.explain_problem(good, [1, 2, 3]))
    short = {"explanations": [{"rank": 1, "one_line": "x", "explanation": "too short"}]}
    assert "words" in str(writing.explain_problem(short, [1]))


def test_source_text_is_capped() -> None:
    wiki = {"lead": "lead " * 3000, "sections": [{"heading": "H", "text": "s " * 3000}]}
    assert len(writing.source_text(wiki).split()) == writing.SOURCE_WORDS
    assert "no Wikipedia" in writing.source_text(None)
