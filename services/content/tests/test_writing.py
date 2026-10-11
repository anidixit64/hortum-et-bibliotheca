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


def test_facts_must_quote_the_source() -> None:
    source = "Ellison wrote the novel in a barn in Vermont. It won the National Book Award in 1953."
    facts = [
        {"fact": "Ellison drafted it in a Vermont barn.",
         "source_sentence": "Ellison wrote the novel in a barn in Vermont."},
        {"fact": "It sold a billion copies.",
         "source_sentence": "It sold a billion copies worldwide."},
        {"fact": "It won the National Book Award.",
         "source_sentence": "it won the National Book Award in 1953"},  # case and dot differ
    ]  # fmt: skip
    kept = writing.grounded(facts, source)
    assert [f["fact"] for f in kept] == [
        "Ellison drafted it in a Vermont barn.",
        "It won the National Book Award.",
    ]
    assert "only 2 facts" in str(writing.facts_problem({"facts": facts}, source))
