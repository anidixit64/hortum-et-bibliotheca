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

VERSION = 3
WIKI_API = "https://en.wikipedia.org/w/api.php"
OPEN_LIBRARY = "https://openlibrary.org/search.json"
COVERS = "https://covers.openlibrary.org/b/id/{}-M.jpg"
FIELDS = (
    "key,title,author_name,first_publish_year,edition_count,ratings_count,"
    "cover_i,isbn,publisher"
)
MAX_LOOKUPS = 10  # cited books looked up in Open Library (1 request a second)
KEEP = 15
SUBJECT_RESULTS = 8
# Further reading, bibliography, and a "Books" section travel with the bibliography,
# not with the article body.
READING_HEADINGS = {
    "further reading",
    "bibliography",
    "selected bibliography",
    "books",
    "selected books",
}
_HEADING = re.compile(r"(?m)^(={2,})\s*(.+?)\s*\1\s*$")
_ITALIC = re.compile(r"''(.+?)''")
_EXCLUDE = re.compile(
    r"\b(proceedings|conference|symposium|colloquium|congress|workshop|"
    r"record books?|yearbooks?|annual reports?|working papers?|dissertations?|theses|thesis)\b",
    re.I,
)
# Noted presses a general reader can find: the 2007 A+ and A lists, matched on the
# publisher field (punctuation folded away). Longer names are checked as phrases.
_NOTED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern))
    for label, pattern in (
        ("Cambridge University Press", r"cambridge university press|\bcup\b"),
        ("University of Chicago Press", r"university of chicago press|univ of chicago press"),
        ("Columbia University Press", r"columbia university press"),
        ("Harvard University Press", r"harvard university press|\bhup\b"),
        ("MIT Press", r"mit press"),
        ("Oxford University Press", r"oxford university press|\boup\b"),
        ("Clarendon Press", r"\bclarendon\b"),
        ("Princeton University Press", r"princeton university press|\bpup\b"),
        ("Stanford University Press", r"stanford university press"),
        (
            "University of California Press",
            r"university of california press|univ of california press",
        ),
        ("Yale University Press", r"yale university press|\byup\b"),
        ("Alfred A. Knopf", r"alfred a knopf|\bknopf\b"),
        ("Allen & Unwin", r"allen (?:and|&) unwin|allen unwin"),
        ("Cornell University Press", r"cornell university press"),
        ("Duke University Press", r"duke university press"),
        ("Edward Elgar", r"edward elgar"),
        ("Elsevier", r"elsevier"),
        ("Johns Hopkins University Press", r"johns hopkins"),
        ("Kluwer", r"kluwer"),
        ("Manchester University Press", r"manchester university press"),
        ("Melbourne University Press", r"melbourne university press"),
        ("New York University Press", r"new york university press|\bnyu press\b"),
        ("Palgrave Macmillan", r"palgrave|st martin s press"),
        ("Politico's", r"politico s"),
        ("Polity Press", r"polity press|\bpolity\b"),
        ("Routledge", r"routledge|taylor (?:and|&) francis|taylor francis"),
        ("Sage Publishing", r"\bsage\b"),
        ("Science Publishers", r"science publishers"),
        ("University of Pennsylvania Press", r"university of pennsylvania press|\bpenn press\b"),
        ("University of Michigan Press", r"university of michigan press"),
        ("University of Minnesota Press", r"university of minnesota press"),
        (
            "University of New South Wales Press",
            r"university of new south wales press|\bunsw press\b",
        ),
        ("University of Toronto Press", r"university of toronto press"),
        ("Wiley-Blackwell", r"wiley blackwell|\bblackwell\b"),
        ("John Wiley & Sons", r"john wiley|\bwiley\b"),
        ("Basic Books", r"basic books"),
        ("Harper & Row", r"harper row|harpercollins|harper collins"),
        ("Pergamon Press", r"pergamon"),
        ("Prentice Hall", r"prentice hall"),
        ("Random House", r"random house"),
        ("Springer", r"springer"),
        ("Academic Press", r"academic press"),
        ("World Health Organization", r"world health organization|\bwho\b"),
    )
)


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


def _fold_pub(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def noted_publisher(text: str | None) -> str | None:
    """The list name when ``text`` names one of the noted presses, else nothing."""
    if not text:
        return None
    folded = _fold_pub(text)
    for label, pattern in _NOTED:
        if pattern.search(folded):
            return label
    return None


def reading_blocks(wikitext: str) -> str:
    """The further-reading, bibliography, and books sections, headings aside."""
    matches = list(_HEADING.finditer(wikitext))
    chunks: list[str] = []
    for i, match in enumerate(matches):
        if match.group(2).strip().lower() not in READING_HEADINGS:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(wikitext)
        chunks.append(wikitext[match.end() : end])
    return "\n".join(chunks)


def reading_entries(wikitext: str) -> list[dict[str, Any]]:
    """Books named in those sections: cite templates, and italic titles with a noted press."""
    block = reading_blocks(wikitext)
    if not block.strip():
        return []
    found = cited_books(block)
    for line in block.splitlines():
        if re.search(r"\{\{\s*cite\s", line, re.I):
            continue
        italic = _ITALIC.search(line)
        if not italic:
            continue
        title = markup.plain(italic.group(1))
        publisher = noted_publisher(line[italic.end() :])
        if not title or not publisher:
            continue
        author = markup.plain(line[: italic.start()]).strip(" *#.")
        found.append(
            {
                "title": title,
                "author": author or None,
                "year": markup.year(line),
                "isbn": None,
                "publisher": publisher,
                "cited": 0,
            }
        )
    return found


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


def _publisher_of(doc: dict[str, Any]) -> str | None:
    pubs = doc.get("publisher") or []
    if isinstance(pubs, str):
        return pubs
    if isinstance(pubs, list):
        return ", ".join(str(p) for p in pubs[:3] if p) or None
    return None


def _match(
    doc: dict[str, Any], source: str, cited: int = 0, publisher: str | None = None
) -> dict[str, Any]:
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
        "publisher": noted_publisher(publisher) or noted_publisher(_publisher_of(doc)),
    }


def score(book: dict[str, Any]) -> float:
    bonus = 2.0 if book.get("source") == "reading" else 0.0
    return float(
        3 * book["cited"]
        + bonus
        + math.log(max(book.get("editions") or 1, 1))
        + math.log(1 + (book.get("ratings") or 0))
    )


def for_public(book: dict[str, Any]) -> bool:
    """A general-market or noted academic book, not a conference record or record book."""
    title = book.get("title") or ""
    if not title or _DICTIONARY.search(title) or _EXCLUDE.search(title):
        return False
    return bool(book.get("publisher"))


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
            match = _match(docs[0], "cited", book["cited"], book.get("publisher"))
            books[match["work"]] = match
        else:  # not in Open Library: the citation still stands on its own
            books[f"cite:{normalize(book['title'])}"] = {
                **book,
                "publisher": noted_publisher(book.get("publisher")),
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

    have = {normalize(b.get("title") or "") for b in books.values()}
    for book in reading_entries(wikitext):
        key = normalize(book["title"])
        if not key or key in have:
            continue
        have.add(key)
        books[f"reading:{key}"] = {
            **book,
            "publisher": noted_publisher(str(book.get("publisher") or "")) or None,
            "editions": 0,
            "ratings": 0,
            "cover": None,
            "open_library": None,
            "work": None,
            "source": "reading",
        }

    kept = [b for b in books.values() if for_public(b)]
    ranked = sorted(kept, key=lambda b: (-score(b), b["title"] or ""))[:KEEP]
    for book in ranked:
        book["score"] = round(score(book), 3)
    return {"books": ranked, "references": references(topic)}
