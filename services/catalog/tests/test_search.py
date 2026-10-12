import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from catalog.config import Settings
from catalog.main import build_app

TOPICS = [
    # id, name, category, description, n_tossups, aliases
    (
        "Q2736",
        "Association football",
        "Pop Culture",
        "team sport",
        9,
        ["association football", "soccer", "football", "futbol"],
    ),
    ("Q308", "Mercury (planet)", "Science", "planet", 27, ["mercury", "mercury planet"]),
    ("Q925", "Mercury (element)", "Science", "chemical element", 43, ["mercury", "hg"]),
    ("Q40556", "Mercury (mythology)", "Mythology", "Roman god", 3, ["mercury", "hermes"]),
    ("Q15869", "Freddie Mercury", "Fine Arts", "singer", 4, ["freddie mercury"]),
    ("Q41", "Social science", "Social Science", "fields", 30, ["social science", "society"]),
    # France's answer lines underline "Republic" in "French Republic".
    ("Q142", "France", "Fine Arts", "country", 263, ["france", "required:republic"]),
    ("Q123397", "Republic (Plato)", "Philosophy", "dialogue", 47, ["republic"]),
]


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    path = tmp_path / "corpus.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE topics (id TEXT PRIMARY KEY, display_name TEXT, primary_category TEXT,
                             description TEXT, n_tossups INTEGER);
        CREATE TABLE topic_aliases (topic_id TEXT, alias_search TEXT, source TEXT);
        CREATE VIRTUAL TABLE topic_aliases_fts USING fts5(
            alias_search, topic_id UNINDEXED, tokenize = 'trigram');
        """
    )
    for tid, name, cat, desc, n, aliases in TOPICS:
        conn.execute("INSERT INTO topics VALUES (?, ?, ?, ?, ?)", (tid, name, cat, desc, n))
        for i, alias in enumerate(aliases):
            source = "title" if i == 0 else "accept"
            if alias.startswith("required:"):
                alias, source = alias.removeprefix("required:"), "required"
            conn.execute("INSERT INTO topic_aliases VALUES (?, ?, ?)", (tid, alias, source))
            conn.execute("INSERT INTO topic_aliases_fts VALUES (?, ?)", (alias, tid))
    conn.commit()
    return path


def search(corpus: Path, q: str) -> list[dict]:
    client = TestClient(build_app(Settings(corpus_path=corpus)))
    response = client.get("/search", params={"q": q})
    assert response.status_code == 200
    return response.json()


def test_typo_finds_soccer(corpus: Path) -> None:
    assert search(corpus, "socer")[0]["name"] == "Association football"


@pytest.mark.parametrize("query", ["soccer", "futbol", "association football", "Soccer!"])
def test_every_alias_finds_the_same_topic(corpus: Path, query: str) -> None:
    assert search(corpus, query)[0]["id"] == "Q2736"


def test_ambiguous_name_returns_every_sense(corpus: Path) -> None:
    ids = [r["id"] for r in search(corpus, "Mercury")[:3]]
    assert set(ids) == {"Q308", "Q925", "Q40556"}
    assert ids[0] == "Q925"  # most questions first among equally good matches


def test_short_query_uses_prefix_match(corpus: Path) -> None:
    assert search(corpus, "hg")[0]["id"] == "Q925"


def test_503_until_corpus_is_built(tmp_path: Path) -> None:
    client = TestClient(build_app(Settings(corpus_path=tmp_path / "missing.db")))
    assert client.get("/search", params={"q": "x"}).status_code == 503


def test_underlined_fragment_ranks_below_a_main_title(corpus: Path) -> None:
    assert search(corpus, "the republic")[0]["name"] == "Republic (Plato)"


def lookup(corpus: Path, names: list[str], exclude: str | None = None) -> dict:
    client = TestClient(build_app(Settings(corpus_path=corpus)))
    response = client.post("/topics/lookup", json={"names": names, "exclude": exclude})
    assert response.status_code == 200
    return {name: link["id"] for name, link in response.json().items()}


def test_names_on_a_page_link_to_their_own_topics(corpus: Path) -> None:
    found = lookup(corpus, ["Freddie Mercury", "France", "Soccer", "The"], exclude="Q41")
    # An exact strong name links; "Soccer" is only an accepted alias, too loose for a
    # single word; "The" is never a name.
    assert found == {"Freddie Mercury": "Q15869", "France": "Q142"}


def test_shared_names_and_the_pages_own_names_do_not_link(corpus: Path) -> None:
    assert lookup(corpus, ["Mercury"]) == {}  # the planet or the element: don't guess
    assert lookup(corpus, ["Social science", "France"], exclude="Q41") == {"France": "Q142"}
    assert lookup(corpus, ["Republic"]) == {"Republic": "Q123397"}  # France's is underlined
