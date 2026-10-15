from content import special

SOURCE = (
    "The war began in 1861 at Fort Sumter. Lee surrendered at Appomattox in 1865. "
    "Rome was founded, by tradition, in 753 BC."
)


def test_timeline_keeps_events_whose_quote_names_their_year() -> None:
    rows = [
        (1865, "Lee surrenders", "Lee surrendered at Appomattox in 1865."),
        (1861, "War begins", "The war began in 1861 at Fort Sumter."),
        (1862, "Wrong year", "The war began in 1861 at Fort Sumter."),
        (1863, "Invented", "Gettysburg was fought in 1863."),
        (-753, "Rome founded", "Rome was founded, by tradition, in 753 BC."),
    ]
    events = [{"year": y, "label": label, "source_sentence": q} for y, label, q in rows]
    kept = special.timeline(events, SOURCE)
    assert [(e["year"], e["label"]) for e in kept] == [
        (-753, "Rome founded"),
        (1861, "War begins"),
        (1865, "Lee surrenders"),
    ]


def test_forms_and_feature_checks() -> None:
    assert special.form("History")[0] == "A handful"
    assert "5 or 6" in special.form("History")[1]
    assert special.form("Literature") == special.DEFAULT_FORM
    assert special.form("Mythology")[0] == "A handful"
    assert not special.is_diagram("History")
    assert special.is_diagram("Science")
    assert special.form("Science")[0] == "Deep dive"
    assert special.form("Science")[2] == "discoveries"
    assert special.form("Philosophy")[0] == "The argument"
    assert special.form("Pop Culture") == special.DEFAULT_FORM
    good = {
        "title": "T",
        "body": " ".join(["w"] * 700),
        "steps": [{"label": "Heat", "detail": "x"}],
    }
    assert special.feature_problem(good) is None
    assert "words" in str(special.feature_problem({**good, "body": "short"}))
    long_step = [{"label": "a very long step label that goes on and on", "detail": "x"}]
    assert "short" in str(special.feature_problem({**good, "steps": long_step}))


def test_diagram_essays_stay_short_and_a_handful_is_five_or_six() -> None:
    assert special.feature_words("Science") == special.SHORT_FEATURE_WORDS
    assert special.feature_words("Social Science") == special.SHORT_FEATURE_WORDS
    assert special.feature_words("Philosophy") == special.FEATURE_WORDS
    short = {"title": "T", "body": " ".join(["w"] * 700)}
    assert "words" in str(special.feature_problem(short, special.SHORT_FEATURE_WORDS))
    entries = [{"name": f"Thing {i}", "text": " ".join(["word"] * 70)} for i in range(6)]
    assert special.entries_problem({"title": "Six things", "entries": entries}) is None
    assert "5 or 6" in str(special.entries_problem({"title": "Few", "entries": entries[:3]}))
    brief = [{**entries[0], "text": "too short"}, *entries[1:]]
    assert "words" in str(special.entries_problem({"title": "Six things", "entries": brief}))
