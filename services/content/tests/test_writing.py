from content import writing
from content.generate import chain


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
    entry = {"one_line": "One line.", "explanation": " ".join(["w"] * 130)}
    good = {"explanations": [{"rank": 1, **entry}, {"rank": 2, **entry}]}
    assert writing.explain_problem(good, [1, 2]) is None
    assert "missing" in str(writing.explain_problem(good, [1, 2, 3]))
    short = {"explanations": [{"rank": 1, "one_line": "x", "explanation": "too short"}]}
    assert "words" in str(writing.explain_problem(short, [1]))


def test_source_text_is_the_lead_then_sections_up_to_a_cap() -> None:
    huge = {"lead": "lead " * 3000, "sections": [{"heading": "H", "text": "s " * 3000}]}
    text = writing.source_text(huge)
    assert len(text.split()) == writing.SOURCE_WORDS
    assert text.startswith("lead") and "H:" not in text
    assert len(writing.source_text(huge, 100).split()) == 100
    short = {
        "lead": "Diocletian ruled.",
        "sections": [{"heading": "Reign", "text": "He abdicated in 305."}],
    }
    assert writing.source_text(short) == "Diocletian ruled. Reign: He abdicated in 305."
    assert writing.lead_text(short) == "Diocletian ruled."
    assert writing.later_text(short) == "Reign: He abdicated in 305."
    assert "Diocletian" not in writing.later_text(short)
    assert writing.later_text({"lead": "Only a lead."}) == "Only a lead."
    assert "no Wikipedia" in writing.source_text(None)
    assert "no Wikipedia" in writing.lead_text(None)
    assert "no Wikipedia" in writing.later_text(None)
    prompt = writing.FACTS.format(name="Diocletian", category="History", source=text)
    assert "exactly 4" in prompt
    assert "conversation" in writing.FACTS_SYSTEM
    assert len(writing.FACTS_SYSTEM) + len(prompt) < chain.GROQ_CHAR_LIMIT


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


def test_blurbs_keep_only_titles_from_the_shelf() -> None:
    from content import blurbs

    titles = ["Invisible Man", "Ralph Ellison: A Biography", "Other"]
    data = {
        "picks": [
            {"title": "invisible man", "blurb": "Read this novel slowly."},
            {"title": "Not a book", "blurb": "Nope."},
            {"title": "Ralph Ellison: A Biography", "blurb": "The life behind the novel."},
        ]
    }
    assert blurbs.problem(data, titles) is None
    assert [b["title"] for b in blurbs.kept(data, titles)] == [
        "Invisible Man",
        "Ralph Ellison: A Biography",
    ]


def test_meta_talk_about_the_quiz_is_caught_but_subject_prose_is_not() -> None:
    caught = [
        "The example mentions ice.",
        "so the answer is war",
        "Question writers use it",
        "the clue Ras",
        "Some questions attribute Masada to Titus",
        "a deliberate distractor",
    ]
    fine = ["Clausewitz wrote On War.", "Players of chess call it a fork.",
            "Socrates asked these questions of everyone.", "a clue to the murderer",
            "This is an example of convergent evolution.",
            "the source of the Nile"]  # fmt: skip
    assert all(writing.meta_phrase(x) for x in caught)
    assert not any(writing.meta_phrase(x) for x in fine)
    entry = {"rank": 1, "one_line": "x", "explanation": " ".join(["w"] * 130) + " the example"}
    assert "the example" in str(writing.explain_problem({"explanations": [entry]}, [1]))
