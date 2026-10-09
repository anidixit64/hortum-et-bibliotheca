import json
import sqlite3
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from hortum_pipeline import answer_stage, facts, grouping, ingest, linking
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import NullReporter
from hortum_pipeline.wiki import HttpCache, WikiClient

UA = "hortum-test/0 (https://example.com/test)"


def page(index: int, title: str, qid: str | None, extract: str, disamb: bool = False) -> dict:
    props: dict = {"wikibase_item": qid} if qid else {}
    if disamb:
        props["disambiguation"] = ""
    return {"index": index, "title": title, "extract": extract, "pageprops": props}


SEARCH = {
    "leo tolstoy": [page(1, "Leo Tolstoy", "Q7243", "Russian author who wrote War and Peace.")],
    "soccer": [
        page(1, "Association football", "Q2736", "Sport played in the World Cup by two teams."),
        page(2, "Soccer (disambiguation)", None, "Soccer may refer to", disamb=True),
    ],
    "mercury": [
        page(1, "Mercury (planet)", "Q308", "Mercury is the planet closest to the Sun."),
        page(2, "Mercury (mythology)", "Q40556", "Roman messenger god with winged sandals."),
        page(3, "Mercury", None, "Mercury may refer to", disamb=True),
    ],
}

SPARQL = {
    "labels": {
        "results": {
            "bindings": [
                {
                    "item": {"value": "http://www.wikidata.org/entity/Q2736"},
                    "desc": {"value": "team sport"},
                    "alias": {"value": "footy"},
                },
            ]
        }
    },
    "dates": {
        "results": {
            "bindings": [
                {
                    "item": {"value": "http://www.wikidata.org/entity/Q7243"},
                    "prop": {"value": "P569"},
                    "time": {"value": "1828-09-09T00:00:00Z"},
                    "precision": {"value": "11"},
                },
            ]
        }
    },
    "places": {
        "results": {
            "bindings": [
                {
                    "item": {"value": "http://www.wikidata.org/entity/Q7243"},
                    "prop": {"value": "P19"},
                    "place": {"value": "http://www.wikidata.org/entity/Q1"},
                    "placeLabel": {"value": "Yasnaya Polyana"},
                    "coord": {"value": "Point(37.523 54.069)"},
                },
            ]
        }
    },
}


# Direct title lookups: "Soccer" redirects; "Mercury" is a disambiguation page.
TITLES = {
    "Soccer": ("Association football", "Q2736", "Sport played in the World Cup by two teams."),
    "Mercury": ("Mercury", None, "Mercury may refer to"),
}


def title_response(requested: list[str]) -> dict:
    normalized, redirects, pages = [], [], []
    for title in requested:
        canonical = title[0].upper() + title[1:]
        if canonical != title:
            normalized.append({"from": title, "to": canonical})
        if canonical not in TITLES:
            pages.append({"title": canonical, "missing": True})
            continue
        target, qid, extract = TITLES[canonical]
        if target != canonical:
            redirects.append({"from": canonical, "to": target})
        props = {"wikibase_item": qid} if qid else {"disambiguation": ""}
        pages.append({"title": target, "extract": extract, "pageprops": props})
    return {"query": {"normalized": normalized, "redirects": redirects, "pages": pages}}


def handler(request: httpx.Request) -> httpx.Response:
    params = parse_qs(urlparse(str(request.url)).query)
    if "titles" in params:
        return httpx.Response(200, json=title_response(params["titles"][0].split("|")))
    if "gsrsearch" in params:
        pages = SEARCH.get(params["gsrsearch"][0], [])
        return httpx.Response(200, json={"query": {"pages": pages}} if pages else {})
    query = params["query"][0]
    kind = "dates" if "timeValue" in query else "places" if "P625" in query else "labels"
    return httpx.Response(200, json=SPARQL[kind])


@pytest.fixture
def linked(settings: PipelineSettings, monkeypatch: pytest.MonkeyPatch) -> PipelineSettings:
    settings = settings.model_copy(update={"wikimedia_user_agent": UA})

    def fake_client(s: PipelineSettings, agent: str) -> WikiClient:
        cache = HttpCache(s.http_cache_dir / "test.db")
        return WikiClient(cache, agent, min_interval=0, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(linking, "make_client", fake_client)
    monkeypatch.setattr(facts, "make_client", fake_client)
    for stage in (ingest, answer_stage, grouping, linking):
        stage.run(settings, NullReporter())
    return settings


def topic_of(conn: sqlite3.Connection, tossup_id: str) -> str:
    return conn.execute(
        "SELECT topic_id FROM tossup_topics WHERE tossup_id = ?", (tossup_id,)
    ).fetchone()[0]


def test_same_name_resolves_by_question_text(linked: PipelineSettings) -> None:
    conn = sqlite3.connect(linked.corpus_path)
    assert topic_of(conn, "t4") == "Q308"  # "closest to the Sun" -> the planet
    assert topic_of(conn, "t5") == "Q40556"  # "winged sandals" -> the god
    assert topic_of(conn, "t2") == "Q2736"


def test_unlinked_answers_become_local_topics(linked: PipelineSettings) -> None:
    conn = sqlite3.connect(linked.corpus_path)
    assert topic_of(conn, "t6") == "local:doctor"


def test_aliases_include_answer_forms_and_title(linked: PipelineSettings) -> None:
    conn = sqlite3.connect(linked.corpus_path)
    aliases = {
        r[0] for r in conn.execute("SELECT alias_search FROM topic_aliases WHERE topic_id='Q2736'")
    }
    assert {"soccer", "association football", "futbol"} <= aliases
    hits = conn.execute(
        "SELECT topic_id FROM topic_aliases_fts WHERE topic_aliases_fts MATCH '\"futbol\"'"
    ).fetchall()
    assert hits == [("Q2736",)]


def test_repeat_run_uses_cache_only(
    linked: PipelineSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request {request.url}")

    def offline_client(s: PipelineSettings, agent: str) -> WikiClient:
        cache = HttpCache(s.http_cache_dir / "test.db")
        return WikiClient(cache, agent, transport=httpx.MockTransport(no_network))

    monkeypatch.setattr(linking, "make_client", offline_client)
    linking.run(linked, NullReporter())


def test_facts_add_dates_places_descriptions_and_aliases(linked: PipelineSettings) -> None:
    facts.run(linked, NullReporter())
    conn = sqlite3.connect(linked.corpus_path)
    rows = conn.execute("SELECT kind, property, value FROM topic_facts WHERE topic_id='Q7243'")
    found = {(k, p): json.loads(v) for k, p, v in rows}
    assert found[("date", "P569")] == {"time": "1828-09-09T00:00:00Z", "precision": 11}
    assert found[("place", "P19")]["label"] == "Yasnaya Polyana"
    assert found[("place", "P19")]["lat"] == pytest.approx(54.069)
    desc = conn.execute("SELECT description FROM topics WHERE id='Q2736'").fetchone()[0]
    assert desc == "team sport"
    hits = conn.execute(
        "SELECT topic_id FROM topic_aliases_fts WHERE topic_aliases_fts MATCH '\"footy\"'"
    ).fetchall()
    assert hits == [("Q2736",)]


def test_link_requires_contact_in_user_agent(settings: PipelineSettings) -> None:
    with pytest.raises(RuntimeError, match="contact details"):
        linking.run(settings, NullReporter())


def test_robot_policy_refusal_explains_itself(tmp_path) -> None:  # type: ignore[no-untyped-def]
    refuse = httpx.MockTransport(
        lambda r: httpx.Response(403, text="Please respect our robot policy https://w.wiki/4wJS")
    )
    client = WikiClient(HttpCache(tmp_path / "c.db"), UA, min_interval=0, transport=refuse)
    with pytest.raises(RuntimeError, match="PIPELINE_WIKIMEDIA_USER_AGENT"):
        client.get_json("https://en.wikipedia.org/w/api.php", {"a": "b"})


def test_exact_title_needs_less_text_overlap() -> None:
    from hortum_pipeline.config import PipelineSettings
    from hortum_pipeline.linking import Candidate, accept_link

    settings = PipelineSettings(_env_file=None)  # type: ignore[call-arg]
    exact = Candidate("France", "Q142", "", 1, False, similarity=0.03, score=0.32, exact_title=True)
    loose = Candidate("Music", "Q638", "", 1, False, similarity=0.03, score=0.32)
    assert accept_link(exact, settings)
    assert not accept_link(loose, settings)


def test_search_hint_follows_subcategory_then_category() -> None:
    from hortum_pipeline.linking import search_hint, search_query

    assert search_hint("Fine Arts", "Auditory Fine Arts") == "music"
    assert search_hint("Philosophy", "Philosophy") == "philosophy"
    assert search_hint("Pop Culture", "Movies") == ""
    assert search_query("The Republic", "philosophy") == "the republic philosophy"


def test_redirect_beats_a_search_hit_about_the_question(
    settings: PipelineSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A soccer question set in a novel shouldn't link the answer to the novel."""
    novel = page(1, "The Silent Cry", "Q1", "Novel in which this sport is played in the World Cup.")
    monkeypatch.setitem(SEARCH, "soccer", [novel])
    settings = settings.model_copy(update={"wikimedia_user_agent": UA})

    def fake_client(s: PipelineSettings, agent: str) -> WikiClient:
        cache = HttpCache(s.http_cache_dir / "redirect.db")
        return WikiClient(cache, agent, min_interval=0, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(linking, "make_client", fake_client)
    for stage in (ingest, answer_stage, grouping, linking):
        stage.run(settings, NullReporter())
    conn = sqlite3.connect(settings.corpus_path)
    assert topic_of(conn, "t2") == "Q2736"


def test_title_lookups_try_without_leading_article() -> None:
    from hortum_pipeline.linking import title_lookups

    assert title_lookups("the moon") == [("the moon", 0.35), ("moon", 0.30)]
    assert title_lookups("“Get Back”") == [("Get Back", 0.35)]
    assert title_lookups("a|b") == []


def test_disambiguation_pages_are_not_direct_hits() -> None:
    from hortum_pipeline.linking import parse_title_lookup

    hits = parse_title_lookup(title_response(["mercury", "soccer", "nothing here"]))
    assert hits["mercury"] is not None and hits["mercury"].disambiguation
    assert hits["soccer"] is not None and hits["soccer"].qid == "Q2736"
    assert hits["nothing here"] is None


def test_facts_rerun_reuses_per_id_store(
    linked: PipelineSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts.run(linked, NullReporter())

    def offline_client(s: PipelineSettings, agent: str) -> WikiClient:
        def no_network(request: httpx.Request) -> httpx.Response:
            raise AssertionError(f"unexpected request {request.url}")

        cache = HttpCache(s.http_cache_dir / "empty.db")  # a cold HTTP cache
        return WikiClient(cache, agent, transport=httpx.MockTransport(no_network))

    monkeypatch.setattr(facts, "make_client", offline_client)
    facts.run(linked, NullReporter())
    conn = sqlite3.connect(linked.corpus_path)
    assert (
        conn.execute("SELECT COUNT(*) FROM topic_facts WHERE topic_id='Q7243'").fetchone()[0] == 2
    )


def test_disambiguated_answer_needs_text_agreement() -> None:
    from hortum_pipeline.config import PipelineSettings
    from hortum_pipeline.linking import Candidate, accept_link, merge_direct

    settings = PipelineSettings(_env_file=None)  # type: ignore[call-arg]
    the_doctor = Candidate("The Doctor", "Q1", "", 1, False, similarity=0.03, score=0.33)
    the_doctor.exact_title = True
    disamb = Candidate("Doctor", "Q2", "", 0, True)
    merged = merge_direct([the_doctor], "doctor", {"doctor": disamb})
    assert all(c.ambiguous for c in merged)
    assert not accept_link(merged[0], settings)


def test_title_store_reuses_cached_batches(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from hortum_pipeline.linking import TitleStore
    from hortum_pipeline.wiki import WIKIPEDIA_API, titles_params

    cache = HttpCache(tmp_path / "http.db")
    batch = ["soccer", "mercury", "nothing here"]
    cache.put(WikiClient.cache_key(WIKIPEDIA_API, titles_params(batch)), title_response(batch))
    store = TitleStore(tmp_path / "titles.db")
    store.seed_from(cache)
    assert all(t in store for t in batch)  # a missing page is remembered too
    hit = store.get("soccer")
    assert hit is not None and hit.qid == "Q2736"
    assert store.get("nothing here") is None


def test_slugs_are_unique_and_the_most_asked_topic_keeps_the_plain_one() -> None:
    from hortum_pipeline.topics import unique_slugs

    slugs = unique_slugs(
        [
            ("Q1539509", "The Invisible Man", 31),
            ("Q1784288", "Invisible Man", 52),
            ("local:invisible-man", "invisible man", 2),
        ]
    )
    assert slugs == {
        "Q1784288": "invisible-man",
        "Q1539509": "the-invisible-man",
        "local:invisible-man": "invisible-man-invisible-man",
    }


@pytest.mark.parametrize(
    ("extract", "kind"),
    [
        ("Barabás is a village in Szabolcs-Szatmár-Bereg county, Hungary.", "settlement"),
        ("Some Like It Hot is a 1959 American crime comedy film.", "film"),
        ("Wynton or Winton is a masculine given name. Notable people with the name", "name"),
        ("Thriller is the sixth studio album by Michael Jackson.", "recording"),
        ("David Mamet is an American playwright, filmmaker and author.", None),
        ("Steven Spielberg is an American film director.", None),
        ("Winterreise is a song cycle for voice and piano.", None),
        ("The Battle of Poitiers was a major English victory.", None),
        ("The Battle of Kursk was a major battle near Kursk. It was the largest single", None),
        ("An elegy is a poem or song of serious reflection.", None),
        ("Tralfamadore is the name of a fictional planet in Vonnegut's novels.", None),
        ("Duck is the common name for numerous species of waterfowl.", None),
        ("Austria is a landlocked country. Vienna is the most populous city.", None),
        ("Molloy or O'Molloy is an Irish surname, anglicised from Ó Maolmhuaidh.", "name"),
        ("Seville is the capital and largest city of Andalusia.", "settlement"),
        ("Monaco is a sovereign city-state and microstate on the French Riviera.", None),
    ],
)
def test_article_kind(extract: str, kind: str | None) -> None:
    assert linking.article_kind(extract) == kind


def test_wrong_kind_of_page_needs_text_agreement_even_on_an_exact_title() -> None:
    from sklearn.feature_extraction.text import TfidfVectorizer

    from hortum_pipeline.linking import Candidate, accept_link, score_candidates

    settings = PipelineSettings(_env_file=None)  # type: ignore[call-arg]
    questions = "Barabas poisons his daughter Abigail in this Marlowe play about Malta."
    vectorizer = TfidfVectorizer(stop_words="english").fit([questions, "a village in Hungary"])
    village = Candidate("Barabás", "Q524336", "Barabás is a village in Hungary.", 1, False)
    village.direct_bonus = 0.35
    group = vectorizer.transform([questions])
    asked = "for 10 points, name this jew of malta title character"
    [scored] = score_candidates(group, [village], {"barabas"}, vectorizer, giveaways=asked)
    assert scored.kind_mismatch and not accept_link(scored, settings)
    # Asked for a place, the same page is fine.
    [scored] = score_candidates(
        group, [village], {"barabas"}, vectorizer, giveaways="name this hungarian village"
    )
    assert not scored.kind_mismatch and accept_link(scored, settings)


def test_a_demotion_moves_a_link_only_to_a_page_titled_for_the_answer() -> None:
    from sklearn.feature_extraction.text import TfidfVectorizer

    from hortum_pipeline.linking import Candidate, score_candidates

    vectorizer = TfidfVectorizer(stop_words="english").fit(
        ["composers michael singer pop thriller nyman tippett", "masculine given name"]
    )
    group = vectorizer.transform(["composers nyman tippett michael singer"])

    def candidates() -> list[Candidate]:
        name_page = Candidate("Michael", "Q1", "Michael is a masculine given name.", 1, False)
        name_page.direct_bonus = 0.35
        singer = Candidate(
            "Michael Jackson", "Q2", "Michael Jackson was an American singer.", 2, False
        )
        return [name_page, singer]

    # The singer only partly matches "Michael": the original order stands.
    ranked = score_candidates(
        group, candidates(), {"michael"}, vectorizer, giveaways="what composer"
    )
    assert ranked[0].title == "Michael" and not ranked[0].promoted
    # Titled for the answer, the same page takes over.
    ranked = score_candidates(
        group, candidates(), {"michael", "michael jackson"}, vectorizer, giveaways="what composer"
    )
    assert ranked[0].title == "Michael Jackson"


def test_same_answer_unlinked_groups_merge_only_when_alike() -> None:
    from hortum_pipeline.topics import homonym_sets

    # plant roots (1, 2) vs polynomial roots (3)
    alike = {frozenset({1, 2}): 0.4, frozenset({1, 3}): 0.02, frozenset({2, 3}): 0.03}
    sets = homonym_sets([1, 2, 3], lambda a, b: alike[frozenset({a, b})], 0.25)
    assert sets == [[1, 2], [3]]
    # sets chain through a shared member
    chain = {frozenset({1, 2}): 0.3, frozenset({1, 3}): 0.0, frozenset({2, 3}): 0.3}
    assert homonym_sets([1, 2, 3], lambda a, b: chain[frozenset({a, b})], 0.25) == [[1, 2, 3]]


@pytest.mark.parametrize(
    ("answer", "short"),
    [
        ("Oscar Fingal O’Flahertie Wills Wilde", "Oscar Wilde"),
        ("John Milton Cage Jr", "John Cage"),
        ("Marc Zakharovich Chagall", "Marc Chagall"),
        ("The Birthday Party", None),
        ("Joan of Arc", None),
        ("Herman Melville", None),  # already two words
        ("Rhapsody on a Theme of Paganini", None),
    ],
)
def test_short_name(answer: str, short: str | None) -> None:
    assert linking.short_name(answer) == short


def test_a_shortened_name_needs_text_agreement() -> None:
    from hortum_pipeline.linking import NAME_FORM_BONUS, Candidate, accept_link

    settings = PipelineSettings(_env_file=None)  # type: ignore[call-arg]
    wilde = Candidate("Oscar Wilde", "Q30875", "", 1, False, similarity=0.02, score=0.3)
    wilde.direct_bonus, wilde.exact_title = NAME_FORM_BONUS, True
    assert not accept_link(wilde, settings)
    wilde.similarity = 0.18
    assert accept_link(wilde, settings)
