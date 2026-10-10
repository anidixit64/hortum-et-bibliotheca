"""Bibliography candidates: books the article cites, matched in Open Library, plus a subject
search. Ranked by ``cited_in_article * 3 + log(editions) + log(1 + ratings)``.

Open Library's subject tags are noisy (a "Prohibition" search returns *Feel the Fear and Do
It Anyway*; "Dreams", a romance novel), so a subject-search book counts only if its title
names the topic, and outside literature fiction and children's books are excluded. Books
cited only as dictionaries (a definition) are dropped.
"""

import math
import re
from collections import Counter
from typing import Any

from content.fetchers import Topic, Unavailable, markup
from content.http import FetchError, PoliteClient
from hortum_common.text import normalize

VERSION = 2
WIKI_API = "https://en.wikipedia.org/w/api.php"
OPEN_LIBRARY = "https://openlibrary.org/search.json"
COVERS = "https://covers.openlibrary.org/b/id/{}-M.jpg"
FIELDS = "key,title,author_name,first_publish_year,edition_count,ratings_count,cover_i,isbn"
MAX_LOOKUPS = 10  # cited books looked up in Open Library (1 request a second)
KEEP = 15
SUBJECT_RESULTS = 8


def cited_books(wikitext: str) -> list[dict[str, Any]]:
    """Every ``{{cite book}}`` (and ``{{citation}}`` with an ISBN), counted by title."""
    found: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    bodies = markup.templates(wikitext, "cite book") + [
        b for b in markup.templates(wikitext, "citation") if "isbn" in b.lower()
    ]
    for body in bodies:
        p = markup.params(body)
        title = p.get("title", "")
        if not title:
            continue
        key = normalize(title)
        counts[key] += 1
        if key in found:
            continue
        author = (
            p.get("author")
            or p.get("author1")
            or " ".join(
                x for x in (p.get("first") or p.get("first1"), p.get("last") or p.get("last1")) if x
            )
        )
        found[key] = {
            "title": title,
            "author": author or p.get("editor") or p.get("editor-last") or None,
            "year": markup.year(p.get("date") or p.get("year") or ""),
            "isbn": re.sub(r"[^0-9Xx]", "", p.get("isbn", "")) or None,
            "publisher": p.get("publisher") or None,
        }
    return [{**book, "cited": counts[key]} for key, book in found.items()]


_DICTIONARY = re.compile(r"\bdictionary\b", re.I)


def names_topic(title: str, topic_name: str) -> bool:
    """The title contains every word of the topic's name (plurals folded): "Dream
    Psychology" names "Dream"; "Icebreaker" doesn't."""
    words = set(normalize(title, singularize=True).split()) | set(normalize(title).split())
    wanted = {normalize(w, singularize=True) for w in normalize(topic_name).split()}
    return bool(wanted) and all(w in words or any(t.startswith(w) for t in words) for w in wanted)


def same_title(a: str, b: str) -> bool:
    """Titles equal ignoring case and punctuation, but not articles: Ellison's "Invisible
    Man" is not Wells's "The Invisible Man"."""
    return _fold(a) == _fold(b)


def _fold(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.lower()).split())


def _match(doc: dict[str, Any], source: str, cited: int = 0) -> dict[str, Any]:
    authors = doc.get("author_name") or []
    return {
        "title": doc.get("title"),
        "author": ", ".join(authors[:2]) or None,
        "year": doc.get("first_publish_year"),
        "isbn": (doc.get("isbn") or [None])[0],
        "editions": doc.get("edition_count") or 0,
        "ratings": doc.get("ratings_count") or 0,
        "cover": COVERS.format(doc["cover_i"]) if doc.get("cover_i") else None,
        "open_library": f"https://openlibrary.org{doc['key']}" if doc.get("key") else None,
        "work": doc.get("key"),
        "cited": cited,
        "source": source,
    }


def score(book: dict[str, Any]) -> float:
    return float(
        3 * book["cited"]
        + math.log(max(book.get("editions") or 1, 1))
        + math.log(1 + (book.get("ratings") or 0))
    )


def references(topic: Topic) -> list[dict[str, str]]:
    """Free reference works worth a look, by category."""
    q = topic.name.replace(" ", "+")
    refs = [
        {"name": "Encyclopaedia Britannica", "url": f"https://www.britannica.com/search?query={q}"}
    ]
    if topic.category == "Philosophy":
        refs.append(
            {
                "name": "Stanford Encyclopedia of Philosophy",
                "url": f"https://plato.stanford.edu/search/searcher.py?query={q}",
            }
        )
    return refs


def fetch(topic: Topic, http: PoliteClient) -> dict[str, Any]:
    if not topic.wikipedia_title:
        raise Unavailable("no Wikipedia article for this topic")
    parsed = http.get_json(
        WIKI_API,
        {
            "action": "parse",
            "page": topic.wikipedia_title,
            "prop": "wikitext",
            "redirects": 1,
            "format": "json",
            "formatversion": 2,
        },
    )
    wikitext = parsed.get("parse", {}).get("wikitext", "")
    books: dict[str, dict[str, Any]] = {}

    cited = sorted(cited_books(wikitext), key=lambda b: -b["cited"])
    for book in cited[:MAX_LOOKUPS]:
        query = {"title": book["title"], "limit": 1, "fields": FIELDS}
        if book["author"]:
            query["author"] = book["author"].split(",")[0]
        try:
            docs = http.get_json(OPEN_LIBRARY, query).get("docs", [])
        except FetchError:
            docs = []
        if docs:
            match = _match(docs[0], "cited", book["cited"])
            books[match["work"]] = match
        else:  # not in Open Library: the citation still stands on its own
            books[f"cite:{normalize(book['title'])}"] = {
                **book,
                "editions": 0,
                "ratings": 0,
                "cover": None,
                "open_library": None,
                "work": None,
                "source": "cited",
            }

    subject = f'subject:"{topic.name}"'
    if topic.category != "Literature":
        subject += ' -subject:"Fiction" -subject:"Juvenile literature" -subject:"Juvenile fiction"'
    searches: list[tuple[dict[str, Any], str]] = [
        ({"q": subject, "limit": SUBJECT_RESULTS * 3, "fields": FIELDS}, "subject")
    ]
    if topic.category == "Literature":  # the work itself: Invisible Man, by Ralph Ellison
        searches.append(({"title": topic.name, "limit": 3, "fields": FIELDS}, "work"))
    for query, source in searches:
        try:
            docs = http.get_json(OPEN_LIBRARY, query).get("docs", [])
        except FetchError:
            continue
        for doc in docs:
            if source == "work" and not same_title(doc.get("title", ""), topic.name):
                continue
            if source == "subject" and not names_topic(doc.get("title", ""), topic.name):
                continue
            if doc.get("key") and doc["key"] not in books:
                books[doc["key"]] = _match(doc, source)

    kept = [b for b in books.values() if not _DICTIONARY.search(b["title"] or "")]
    ranked = sorted(kept, key=lambda b: (-score(b), b["title"] or ""))[:KEEP]
    for book in ranked:
        book["score"] = round(score(book), 3)
    return {"books": ranked, "references": references(topic)}
