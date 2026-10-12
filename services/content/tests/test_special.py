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
    assert special.form("History")[0] == "Be there"
    assert special.form("Science")[2] == "discoveries"
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


def test_history_and_science_features_are_short() -> None:
    assert special.feature_words("History") == special.SHORT_FEATURE_WORDS
    assert special.feature_words("Science") == special.SHORT_FEATURE_WORDS
    assert special.feature_words("Literature") == special.FEATURE_WORDS
    short = {"title": "T", "body": " ".join(["w"] * 700)}
    assert "words" in str(special.feature_problem(short, special.SHORT_FEATURE_WORDS))
