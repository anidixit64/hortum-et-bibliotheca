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


def handler(request: httpx.Request) -> httpx.Response:
    params = parse_qs(urlparse(str(request.url)).query)
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
