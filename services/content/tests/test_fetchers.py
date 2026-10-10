import sqlite3
from typing import Any

import httpx
import pytest

from content.fetchers import Topic, Unavailable, books, images, markup, videos, wiki

INVISIBLE_MAN = Topic(
    "Q1784288",
    "Invisible Man",
    "Invisible Man",
    "Q1784288",
    "Literature",
    "1952 novel by Ralph Ellison",
)


def test_templates_and_params_handle_nesting() -> None:
    text = (
        "x {{Cite book |last=Bell |first=David A. |title=The [[First Total War|First Total War]]"
        " |date=2007 |isbn=978-0-618-34965-4 |ref={{harvnb|Bell|2007}}}} y {{cite book|title=B}}"
    )
    bodies = markup.templates(text, "cite book")
    assert len(bodies) == 2
    p = markup.params(bodies[0])
    assert p["title"] == "The First Total War" and p["first"] == "David A."
    assert markup.year(p["date"]) == 2007
    assert markup.plain("''[[Ralph Ellison]]'' wrote<ref>x</ref> it.") == "Ralph Ellison wrote it."


def test_wiki_splits_lead_and_sections() -> None:
    extract = "Lead text.\n\n== Background ==\nWhy.\n\n=== Detail ===\nMore.\n\n== References ==\nx"
    lead, sections = wiki.sections(extract)
    assert lead == "Lead text."
    assert sections == [{"heading": "Background", "text": "Why.\n\nDetail\nMore."}]


def test_wiki_fetch_and_no_article(conn: sqlite3.Connection, web: Any) -> None:
    http = web(
        conn,
        lambda r: {
            "query": {
                "pages": [
                    {
                        "title": "Invisible Man",
                        "fullurl": "https://en.wikipedia.org/wiki/Invisible_Man",
                        "extract": (
                            "Invisible Man is Ralph Ellison's first novel."
                            "\n\n== Plot ==\nHe lives underground."
                        ),
                    }
                ]
            }
        },
    )
    out = wiki.fetch(INVISIBLE_MAN, http)
    assert out["lead"].startswith("Invisible Man is") and out["sections"][0]["heading"] == "Plot"
    assert out["license"] == "CC BY-SA 4.0"
    with pytest.raises(Unavailable):
        wiki.fetch(Topic("local:x", "x", None, None, None, None), http)


def test_images_skip_chrome_and_keep_credit(conn: sqlite3.Connection, web: Any) -> None:
    def handler(request: httpx.Request) -> Any:
        if request.url.params["prop"] == "pageimages|images":
            return {
                "query": {
                    "pages": [
                        {
                            "pageimage": "Invisible_Man_(1952_1st_ed_jacket_cover).jpg",
                            "images": [
                                {"title": "File:Invisible Man (1952 1st ed jacket cover).jpg"},
                                {"title": "File:Wikiquote-logo.svg"},
                                {"title": "File:Ralph Ellison photo portrait seated.jpg"},
                                {"title": "File:Tiny.jpg"},
                            ],
                        }
                    ]
                }
            }
        assert "Wikiquote" not in request.url.params["titles"]

        def info(title: str, width: int, meta: dict[str, str]) -> dict[str, Any]:
            return {
                "title": title,
                "imageinfo": [
                    {
                        "mime": "image/jpeg",
                        "width": width,
                        "height": 900,
                        "url": f"https://x/{title}",
                        "descriptionurl": f"https://commons/{title}",
                        "extmetadata": {k: {"value": v} for k, v in meta.items()},
                    }
                ],
            }

        return {
            "query": {
                "pages": [
                    info(
                        "File:Invisible Man (1952 1st ed jacket cover).jpg",
                        1869,
                        {"LicenseShortName": "Public domain", "AttributionRequired": "false"},
                    ),
                    info(
                        "File:Ralph Ellison photo portrait seated.jpg",
                        1920,
                        {
                            "LicenseShortName": "CC BY-SA 3.0",
                            "Artist": "<a href='x'>USIA</a>",
                            "AttributionRequired": "true",
                        },
                    ),
                    info("File:Tiny.jpg", 120, {}),
                ]
            }
        }

    out = images.fetch(INVISIBLE_MAN, web(conn, handler))["images"]
    assert [i["file"] for i in out] == [
        "File:Invisible Man (1952 1st ed jacket cover).jpg",
        "File:Ralph Ellison photo portrait seated.jpg",
    ]
    assert out[0]["is_main"] and out[1]["artist"] == "USIA" and out[1]["attribution_required"]


WIKITEXT = """
{{cite book|title=Ralph Ellison and the Politics of the Novel|author=Herbert William Rice
|date=2003|isbn=9780739106549}}
x {{cite book|title=Ralph Ellison and the Politics of the Novel|author=Herbert William Rice}}
{{cite book|title=Obscure Pamphlet|last=Nobody}}
"""


def test_books_rank_cited_then_popular(conn: sqlite3.Connection, web: Any) -> None:
    assert [b["cited"] for b in books.cited_books(WIKITEXT)] == [2, 1]

    def handler(request: httpx.Request) -> Any:
        q = request.url.params
        if "wikipedia" in request.url.host:
            return {"parse": {"wikitext": WIKITEXT}}
        if q.get("title") == "Ralph Ellison and the Politics of the Novel":
            return {
                "docs": [
                    {
                        "key": "/works/OL3508463W",
                        "title": q["title"],
                        "author_name": ["Herbert William Rice"],
                        "edition_count": 1,
                        "cover_i": 4304650,
                    }
                ]
            }
        if q.get("title") == "Invisible Man":
            return {
                "docs": [
                    {
                        "key": "/works/OL1W",
                        "title": "Invisible man",
                        "author_name": ["Ralph Ellison"],
                        "edition_count": 120,
                        "ratings_count": 300,
                    },
                    {
                        "key": "/works/OL2W",
                        "title": "The Invisible Man",
                        "author_name": ["H. G. Wells"],
                        "edition_count": 900,
                    },
                ]
            }
        if q.get("q", "").startswith("subject:"):
            return {
                "docs": [
                    {
                        "key": "/works/OL9W",
                        "title": "A casebook on Invisible man",
                        "edition_count": 1,
                    },
                    {"key": "/works/OL8W", "title": "Feel the fear", "edition_count": 40},
                ]
            }
        return {"docs": []}

    out = books.fetch(INVISIBLE_MAN, web(conn, handler))
    titles = [b["title"] for b in out["books"]]
    # Ellison's novel (120 editions, 300 ratings) outranks a book cited twice; Wells's novel,
    # whose title only looks alike, isn't the work itself.
    assert titles[:2] == ["Invisible man", "Ralph Ellison and the Politics of the Novel"]
    assert "The Invisible Man" not in titles and "Obscure Pamphlet" in titles
    assert "A casebook on Invisible man" in titles and "Feel the fear" not in titles
    rice = out["books"][1]
    assert rice["cover"] == "https://covers.openlibrary.org/b/id/4304650-M.jpg"
    assert rice["cited"] == 2 and rice["source"] == "cited"
    assert out["references"][0]["name"] == "Encyclopaedia Britannica"


def test_videos(conn: sqlite3.Connection, web: Any) -> None:
    with pytest.raises(Unavailable):
        videos.fetch(INVISIBLE_MAN, web(conn, lambda r: {}), "", ["CrashCourse"])
    assert videos.seconds("PT12M30S") == 750 and videos.seconds("PT1H") == 3600

    def handler(request: httpx.Request) -> Any:
        if request.url.path.endswith("/search"):

            def item(vid: str, ch: str, title: str) -> dict[str, Any]:
                return {
                    "id": {"videoId": vid},
                    "snippet": {"title": title, "channelTitle": ch},
                }

            return {
                "items": [
                    item("a", "Random Vlogs", "Invisible Man review!!!"),
                    item("b", "CrashCourse", "Invisible Man: Crash Course Literature 1"),
                    item("c", "TED-Ed", "Why read Invisible Man?"),
                    item("d", "CrashCourse", "Invisible Man part 2"),
                ]
            }
        durations = {"a": "PT9M", "b": "PT12M", "c": "PT5M", "d": "PT2M"}
        return {
            "items": [
                {"id": v, "contentDetails": {"duration": d}, "statistics": {"viewCount": "100"}}
                for v, d in durations.items()
            ]
        }

    out = videos.fetch(INVISIBLE_MAN, web(conn, handler), "key", ["CrashCourse", "TED-Ed"])
    # Allowlisted channels only (the second search's results would need the topic in the
    # title); "d" is too short; CrashCourse ranks above TED-Ed.
    assert [v["id"] for v in out["videos"]] == ["b", "c"]
    assert out["videos"][0]["embed"] == "https://www.youtube-nocookie.com/embed/b"


def test_names_topic() -> None:
    assert books.names_topic("Dream Psychology", "Dream")
    assert books.names_topic("Lucid dreaming", "Dream")
    assert books.names_topic("A casebook on Ralph Ellison's Invisible man", "Invisible Man")
    assert not books.names_topic("Icebreaker", "Dream")
    assert not books.names_topic("Feel the fear and do it anyway", "Prohibition")
