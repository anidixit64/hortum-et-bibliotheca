"""The shelf: every book in the article's bibliography, sources, further reading, and
citations, kept only when its publisher is one a general reader can find.

Ranked by ``cited_in_article * 3 + log(editions) + log(1 + ratings)``. Open Library fills
in covers for the most-cited of those; it does not decide which books stay. A subject
search can add a few more whose titles name the topic, but never by pushing a bibliography
book off the shelf. Subject tags are noisy (a "Prohibition" search returns *Feel the Fear
and Do It Anyway*), so a subject-search book counts only if its title names the topic, and
outside literature fiction and children's books are excluded. Dictionaries, conference
proceedings, and record books are dropped.
"""

import math
import re
from collections import Counter
from typing import Any

from content.fetchers import Topic, Unavailable, markup
from content.http import FetchError, PoliteClient
from hortum_common.text import normalize

VERSION = 4
WIKI_API = "https://en.wikipedia.org/w/api.php"
OPEN_LIBRARY = "https://openlibrary.org/search.json"
COVERS = "https://covers.openlibrary.org/b/id/{}-M.jpg"
FIELDS = (
    "key,title,author_name,first_publish_year,edition_count,ratings_count,cover_i,isbn,publisher"
)
MAX_LOOKUPS = 40  # noted books given an Open Library cover (1 request a second)
KEEP = 100
SUBJECT_RESULTS = 8
# A citation-style article keeps its books under Sources; others use Bibliography,
# Further reading, Works cited, or References. Subsections belong to the parent.
READING_HEADINGS = {
    "further reading",
    "additional reading",
    "bibliography",
    "selected bibliography",
    "annotated bibliography",
    "works cited",
    "sources",
    "books",
    "selected books",
    "references",
}
_PERIODICAL = ("journal", "newspaper", "magazine", "periodical", "website", "encyclopedia")
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
        ("Viking", r"\bviking\b"),
        ("Crown", r"\bcrown\b"),
        ("Portfolio", r"\bportfolio\b"),
        ("Riverhead Books", r"riverhead"),
        ("Avery", r"\bavery\b"),
        ("Simon & Schuster", r"simon (?:and|&) schuster|simon schuster"),
        ("Scribner", r"\bscribner\b"),
        ("Avid Reader Press", r"avid reader"),
        ("Atria Books", r"\batria\b"),
        ("One Signal Publishers", r"one signal"),
        ("PublicAffairs", r"publicaffairs|public affairs"),
        ("Little, Brown and Company", r"little brown"),
        ("Twelve", r"\btwelve\b"),
        ("Farrar, Straus and Giroux", r"farrar|fsg\b"),
        ("Henry Holt and Company", r"henry holt|\bholt\b"),
        ("Metropolitan Books", r"metropolitan books"),
        ("Flatiron Books", r"flatiron"),
        ("St. Martin's Press", r"st martin"),
        ("Ecco", r"\becco\b"),
        ("Harper Business", r"harper business"),
        ("Dey Street Books", r"dey street"),
        ("W. W. Norton", r"norton"),
        ("Bloomsbury", r"bloomsbury"),
        ("Grove Atlantic", r"grove atlantic|\bgrove press\b"),
        ("Profile Books", r"profile books"),
        ("The New Press", r"the new press"),
        ("Beacon Press", r"beacon press"),
        ("Verso Books", r"\bverso\b"),
        ("Haymarket Books", r"haymarket"),
        ("Seven Stories Press", r"seven stories"),
        ("Island Press", r"island press"),
        ("O'Reilly Media", r"o reilly"),
        ("National Geographic Books", r"national geographic"),
        ("Timber Press", r"timber press"),
        ("Phaidon Press", r"phaidon"),
        ("Taschen", r"taschen"),
        ("Thames & Hudson", r"thames (?:and|&) hudson|thames hudson"),
        ("Rizzoli", r"rizzoli"),
        ("Chronicle Books", r"chronicle books"),
        ("Graywolf Press", r"graywolf"),
        ("Coffee House Press", r"coffee house"),
        ("Melville House", r"melville house"),
        ("Catapult", r"\bcatapult\b"),
    )
)


def _citation_is_book(body: str) -> bool:
    """A ``{{citation}}`` that names a book, not a journal, news story, or web page."""
    params = markup.params(body)
    if any(params.get(key) for key in _PERIODICAL):
        return False
    return bool(params.get("title")) and bool(params.get("isbn") or params.get("publisher"))


def cited_books(wikitext: str) -> list[dict[str, Any]]:
    """Every ``{{cite book}}`` and book-like ``{{citation}}``, counted by title."""
    found: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    bodies = markup.templates(wikitext, "cite book") + [
        b for b in markup.templates(wikitext, "citation") if _citation_is_book(b)
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


def _reading_heading(title: str) -> bool:
    name = " ".join(title.strip().lower().split())
    if name in READING_HEADINGS:
        return True
    return any(
        name.startswith(heading + " ") or name.endswith(" " + heading)
        for heading in READING_HEADINGS
    )


def reading_blocks(wikitext: str) -> str:
    """Bibliography, sources, further reading, and books, subsections included."""
    matches = list(_HEADING.finditer(wikitext))
    chunks: list[str] = []
    for i, match in enumerate(matches):
        if not _reading_heading(match.group(2)):
            continue
        level = len(match.group(1))
        end = len(wikitext)
        for nxt in matches[i + 1 :]:
            if len(nxt.group(1)) <= level:
                end = nxt.start()
                break
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


def _blank(book: dict[str, Any], source: str) -> dict[str, Any]:
    publisher = noted_publisher(str(book.get("publisher") or ""))
    return {
        "title": (book.get("title") or "").strip(),
        "author": book.get("author"),
        "year": book.get("year"),
        "isbn": book.get("isbn"),
        "cited": int(book.get("cited") or 0),
        "editions": int(book.get("editions") or 0),
        "ratings": int(book.get("ratings") or 0),
        "cover": book.get("cover"),
        "open_library": book.get("open_library"),
        "work": book.get("work"),
        "source": source,
        "publisher": publisher,
    }


def _keep_public(shelf: dict[str, dict[str, Any]], book: dict[str, Any], source: str) -> None:
    """Add a book whose publisher is on the noted list, merging a repeat of the same title."""
    item = _blank(book, source)
    key = normalize(item["title"])
    if not key or not for_public(item):
        return
    prev = shelf.get(key)
    if prev is None:
        shelf[key] = item
        return
    prev["cited"] = max(int(prev["cited"]), item["cited"])
    if source == "reading":
        prev["source"] = "reading"
    if item["editions"] > int(prev["editions"]):
        prev["editions"] = item["editions"]
        prev["ratings"] = item["ratings"]
    for field in ("author", "year", "isbn", "cover", "open_library", "work"):
        if not prev.get(field) and item.get(field):
            prev[field] = item[field]


def _attach_cover(book: dict[str, Any], http: PoliteClient) -> None:
    """Open Library cover and edition counts. The citation stays if the lookup misses."""
    if book.get("open_library"):
        return
    query: dict[str, Any] = {"title": book["title"], "limit": 1, "fields": FIELDS}
    if book.get("author"):
        query["author"] = str(book["author"]).split(",")[0]
    try:
        docs = http.get_json(OPEN_LIBRARY, query).get("docs", [])
    except FetchError:
        docs = []
    if not docs:
        return
    match = _match(docs[0], book["source"], book["cited"], book.get("publisher"))
    book["editions"] = match["editions"]
    book["ratings"] = match["ratings"]
    book["cover"] = match["cover"]
    book["open_library"] = match["open_library"]
    book["work"] = match["work"]
    book["isbn"] = book.get("isbn") or match.get("isbn")
    if not book.get("author"):
        book["author"] = match.get("author")
    if not book.get("year"):
        book["year"] = match.get("year")


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
    shelf: dict[str, dict[str, Any]] = {}
    for book in cited_books(wikitext):
        _keep_public(shelf, book, "cited")
    for book in reading_entries(wikitext):
        _keep_public(shelf, book, "reading")

    # Covers for the most-cited noted books. The rest of the shelf stays either way.
    by_cited = sorted(shelf.values(), key=lambda b: (-int(b["cited"]), b["title"] or ""))
    for book in by_cited[:MAX_LOOKUPS]:
        _attach_cover(book, http)

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
            _keep_public(shelf, _match(doc, source), source)

    # A subject hit can outrank a cited book. It cannot take one's place.
    ranked = sorted(shelf.values(), key=lambda b: (-score(b), b["title"] or ""))
    core = [b for b in ranked if b["source"] in {"cited", "reading"}]
    extra = [b for b in ranked if b["source"] not in {"cited", "reading"}]
    chosen = core[:KEEP]
    chosen.extend(extra[: max(0, KEEP - len(chosen))])
    chosen.sort(key=lambda b: (-score(b), b["title"] or ""))
    for book in chosen:
        book["score"] = round(score(book), 3)
    return {"books": chosen, "references": references(topic)}
