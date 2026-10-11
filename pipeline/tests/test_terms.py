from collections import Counter

import pytest

from hortum_pipeline import terms
from hortum_pipeline.terms import Candidate, Sentence


@pytest.mark.parametrize(
    ("form", "key"),
    [
        ("General Nelson A. Miles", ("nelson", "miles")),
        ("Nelson Miles", ("nelson", "miles")),
        ("C. S. Fly", ("c", "s", "fly")),
        ("H II regions", ("h", "ii", "region")),
        ("The Mysterious Affair at Styles", ("mysterious", "affair", "at", "styles")),
        ("womb chambers", ("womb", "chamber")),
        ("Burnside's Bridge", ("burnside", "bridge")),
        ("alpha-beta pruning", ("alpha", "beta", "pruning")),
    ],
)
def test_key_of(form: str, key: tuple[str, ...]) -> None:
    assert terms.key_of(form) == key


def candidates(*specs: tuple[str, set[int], str | None]) -> dict[tuple[str, ...], Candidate]:
    out = {}
    for form, sentences, known in specs:
        key = terms.key_of(form)
        out[key] = Candidate(key, set(sentences), Counter({form: len(sentences)}))
        if known:
            out[key].names_topic[known] += 1
    return out


def labels(groups: list[list[Candidate]]) -> set[frozenset[str]]:
    return {frozenset(f for c in g for f in c.forms) for g in groups}


def test_a_short_name_alone_stays_its_own_clue() -> None:
    """ "Willy" may be another Willy than Willy Wonka: a lone short name isn't folded in
    (within one sentence, ``drop_nested`` removes it instead)."""
    groups = terms.merge(candidates(("Nelson Miles", {1, 2, 3}, None), ("Miles", {4}, None)))
    assert labels(groups) == {frozenset({"Nelson Miles"}), frozenset({"Miles"})}


def test_a_short_form_used_more_than_the_full_name_stands_alone() -> None:
    groups = terms.merge(
        candidates(("Mexico", {1, 2, 3, 4}, None), ("Robledo Mountains of New Mexico", {5}, None))
    )
    assert len(groups) == 2


def test_not_across_a_possessive() -> None:
    groups = terms.merge(candidates(("Burnside", {1}, None), ("Burnside's Bridge", {2, 3}, None)))
    assert len(groups) == 2


def test_geographic_heads_and_the_shortest_container() -> None:
    groups = terms.merge(
        candidates(
            ("Cascades", {1}, None),
            ("Cascade Mountains", {2}, None),
            ("Exhorter", {3}, None),
            ("Ras the Exhorter", {4, 5}, None),
            ("nationalist Ras the Exhorter", {6}, None),
        )
    )
    # After "the" a short form may be another thing ("Pliny the Elder" / "elder"), so
    # "Exhorter" on its own stays apart; the described form joins its name.
    assert labels(groups) == {
        frozenset({"Cascades", "Cascade Mountains"}),
        frozenset({"Ras the Exhorter", "nationalist Ras the Exhorter"}),
        frozenset({"Exhorter"}),
    }


def test_two_names_of_one_known_topic_merge() -> None:
    groups = terms.merge(
        candidates(("Filiki Eteria", {1, 2}, "Q1"), ("Friendly Society", {3}, "Q1"))
    )
    assert len(groups) == 1


def test_near_spellings() -> None:
    keys = [("battle", "royal"), ("battle", "royale"), ("murti",), ("murtis",), ("royal",)]
    pairs = {frozenset(p) for p in terms.near_spellings(keys)}
    assert frozenset({("battle", "royal"), ("battle", "royale")}) in pairs
    assert frozenset({("murti",), ("murtis",)}) in pairs
    assert len(pairs) == 2  # a single word never gains an "e"


def test_rank_topic_counts_questions_not_mentions() -> None:
    def sentence(i: int, tossup: str, text: str) -> Sentence:
        return Sentence(i, tossup, f"set-{tossup}", 0.1 * i, 0, 0, 5, 2020, text)

    sentences = [
        sentence(0, "q1", "Nelson Miles accepted his surrender."),
        sentence(1, "q1", "Miles sent him to Fort Sill."),
        sentence(2, "q2", "General Nelson A. Miles chased him."),
        sentence(3, "q3", "He lived at Fort Sill."),
        sentence(4, "q4", "He died at Fort Sill."),
    ]
    found = [
        {"Nelson Miles"},
        {"Miles", "Fort Sill"},
        {"General Nelson A. Miles"},
        {"Fort Sill"},
        {"Fort Sill"},
    ]
    clues = terms.rank_topic("Q2791", sentences, found, lambda form: True, {})
    assert [(c["label"], c["n_questions"]) for c in clues] == [
        ("Fort Sill", 3),
        ("Nelson Miles", 2),
        ("Miles", 1),
    ]
    assert clues[1]["n_mentions"] == 2


def test_reused_wording_counts_once() -> None:
    same = "Nelson Miles accepted his surrender."
    sentences = [
        Sentence(0, "q1", "s1", 0.1, 0, 0, 5, 2020, same),
        Sentence(1, "q2", "s2", 0.1, 0, 0, 5, 2021, same),
        Sentence(2, "q3", "s3", 0.1, 0, 0, 5, 2022, "Miles chased him with Nelson Miles."),
    ]
    clues = terms.rank_topic("Q2791", sentences, [{"Nelson Miles"}] * 3, lambda f: True, {})
    assert clues[0]["n_questions"] == 2


def test_the_answers_own_name_is_never_a_clue() -> None:
    sentences = [Sentence(0, "q1", "s1", 0.1, 0, 0, 5, 2020, "Geronimo led raids.")]
    clues = terms.rank_topic(
        "Q2791",
        sentences,
        [{"Geronimo"}],
        lambda f: True,
        {"geronimo": "Q2791"},
        own_names=frozenset({"geronimo"}),
    )
    assert clues == []


def test_a_term_inside_a_longer_one_in_the_same_sentence_is_dropped() -> None:
    assert terms.drop_nested({"Saha", "Saha equation", "plasma"}) == {"Saha equation", "plasma"}
    assert terms.drop_nested({"Mexico", "Robledo Mountains of New Mexico"}) == {
        "Robledo Mountains of New Mexico"
    }
    assert terms.drop_nested({"Burnside", "Burnside's Bridge"}) == {"Burnside", "Burnside's Bridge"}


def test_trim_and_hyphen_cuts() -> None:
    assert terms.trim("Baldwin's The Fire Next Time") == "The Fire Next Time"
    assert terms.trim("architect Al-Sahili") == "Al-Sahili"
    assert terms.trim("sphincter of Oddi") == "sphincter of Oddi"
    assert terms.trim('heroic" key') == "heroic key"
    assert terms._cut_at_hyphen("fleur-de", "a fleur-de-lis banner")


def test_specific_lowercase_clues() -> None:
    from hortum_pipeline import phrases

    freq = phrases.DocFrequency(
        [f"the size of clue {i}" for i in range(20_000)]
        + ["the radius"] * 5
        + ["circumambulation rituals"] * 2
    )
    assert not terms.specific("radius", 5, 5, 100_000, freq)  # common, not concentrated
    assert not terms.specific("radius", 5, 400, 1000, freq)  # common words never, now
    assert terms.specific("circumambulation rituals", 2, 2, 50, freq)
    assert not terms.specific("circumambulation rituals", 1, 1, 50, freq)  # one question
    assert terms.specific("Nelson Miles", 1, 1, 50, freq)  # names always


def test_one_letter_name_typos_merge() -> None:
    keys = [
        ("Vincente", "de", "Valverde"),
        ("Vicente", "de", "Valverde"),
        ("Prussia",),
        ("Russia",),
    ]
    pairs = {frozenset(p) for p in terms.near_spellings(keys)}
    assert pairs == {frozenset({("Vincente", "de", "Valverde"), ("Vicente", "de", "Valverde")})}


def test_completion_must_name_its_sentences() -> None:
    group = [Candidate(("France",), {0, 1, 2}, Counter({"France": 3}))]
    texts = [
        "Marie de France wrote a lai about this man.",
        "He was sent to France as a child.",
        "He sailed for France with Gouvernail.",
    ]
    assert terms.choose_label(group, texts)[0] == "France"


def test_two_described_things_dont_merge_into_their_shared_name() -> None:
    groups = terms.merge(
        candidates(
            ("Gibbs", {1}, None),
            ("Gibbs paradox", {2, 3}, None),
            ("Gibbs free energy", {4}, None),
        )
    )
    assert len(groups) == 3


def test_short_forms_inside_other_names_stay_apart() -> None:
    assert (
        len(terms.merge(candidates(("Thebes", {1}, None), ("Sacred Band of Thebes", {2, 3}, None))))
        == 2
    )
    assert (
        len(
            terms.merge(candidates(("Callisthenes", {1}, None), ("Pseudo-Callisthenes", {2}, None)))
        )
        == 2
    )
    assert (
        len(terms.merge(candidates(("Hydaspes", {1, 2, 3}, None), ("Hydaspes River", {4}, None))))
        == 1
    )


def test_pairs_credit_each_person() -> None:
    groups = terms.merge(
        candidates(
            ("Out of the Silent Planet", {1}, None),
            ("Out of the Silent Planet and Perelandra", {2}, None),
        )
    )
    assert labels(groups) == {frozenset({"Out of the Silent Planet"}), frozenset({"Perelandra"})}


def test_one_word_typos() -> None:
    pairs = {
        frozenset(p)
        for p in terms.near_spellings([("simurgh",), ("simorgh",), ("prussia",), ("russia",)])
    }
    assert pairs == {frozenset({("simurgh",), ("simorgh",)})}
