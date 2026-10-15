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
    assert special.form("Literature")[0] == "A handful"
    assert special.form("Mythology")[0] == "A handful"
    assert special.form("Pop Culture")[0] == "A handful"
    assert special.form("Science")[0] == "A handful"
    assert special.form("Philosophy")[0] == "A handful"
    assert special.form("Social Science")[0] == "A handful"
    assert special.form("Science")[2] == "discoveries"
    assert special.form("Philosophy")[2] == "events"
    assert special.is_diagram("History")
    assert special.is_diagram("Science")
    assert special.is_diagram("Literature")
    assert special.is_diagram(None)


def test_a_handful_is_five_or_six_and_a_diagram_keeps_its_steps() -> None:
    entries = [{"name": f"Thing {i}", "text": " ".join(["word"] * 70)} for i in range(6)]
    assert special.entries_problem({"title": "Six things", "entries": entries}) is None
    assert "5 or 6" in str(special.entries_problem({"title": "Few", "entries": entries[:3]}))
    brief = [{**entries[0], "text": "too short"}, *entries[1:]]
    assert "words" in str(special.entries_problem({"title": "Six things", "entries": brief}))
    steps = [
        {"label": "Question", "detail": "What is known."},
        {"label": "Premise", "detail": "What is granted."},
        {"label": "Conclusion", "detail": "What follows."},
    ]
    blurb = " ".join(["word"] * 150)
    drawn = {
        "title": "Six things",
        "entries": entries,
        "diagram_title": "How a lens bends a ray",
        "steps": steps,
        "diagram_blurb": blurb,
    }
    assert special.entries_problem(drawn, diagram=True) is None
    missing_steps = special.entries_problem(
        {"title": "Six things", "entries": entries, "diagram_title": "How a lens bends a ray",
         "steps": [], "diagram_blurb": blurb},
        diagram=True,
    )
    assert "diagram" in str(missing_steps)
    long_step = [{"label": "a very long step label that goes on and on", "detail": "x"}, *steps]
    assert "short" in str(
        special.entries_problem({**drawn, "steps": long_step}, diagram=True)
    )
    short_blurb = " ".join(["word"] * 40)
    short = special.entries_problem({**drawn, "diagram_blurb": short_blurb}, diagram=True)
    assert short is not None and "blurb" in short
    long_blurb = " ".join(["word"] * 260)
    missing_title = special.entries_problem({**drawn, "diagram_title": ""}, diagram=True)
    assert missing_title is not None and "title" in missing_title
    long = special.entries_problem({**drawn, "diagram_blurb": long_blurb}, diagram=True)
    assert long is not None and "blurb" in long
