"""Stage 4: link candidate groups to Wikipedia/Wikidata, then build topics.

First every answer is looked up directly as a Wikipedia title, following redirects
("Soccer" -> "Association football"); then, per group, a search returns the top hits
with their intro text and Wikidata ID. Each candidate is scored by TF-IDF similarity
between its intro and the group's own questions, plus bonuses for a direct title hit or
a matching title. Groups that resolve to the same Wikidata item merge into one topic.
"""

import gzip
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize as l2_normalize

from hortum_common.text import normalize
from hortum_pipeline import db, topics
from hortum_pipeline.clues import split_question
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import Reporter
from hortum_pipeline.wiki import (
    TITLE_BATCH,
    WIKIPEDIA_API,
    HttpCache,
    WikiClient,
    search_params,
    titles_params,
)

SCHEMA = """
DROP TABLE IF EXISTS group_links;
CREATE TABLE group_links (
    group_id INTEGER PRIMARY KEY REFERENCES candidate_groups(id),
    status TEXT NOT NULL,      -- linked | no_match | skipped
    qid TEXT,
    title TEXT,
    score REAL,
    similarity REAL,
    candidates TEXT NOT NULL   -- JSON: every scored hit, for debugging thresholds
);
"""

_SEARCH_SYNTAX = re.compile(r'["~*?\\:]|^[-!+]+')
_BAD_TITLE = re.compile(r"[#<>\[\]|{}]")
_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.I)
_PAREN = re.compile(r"\s*\([^()]*\)\s*$")


@dataclass
class Candidate:
    title: str
    qid: str | None
    extract: str
    rank: int
    disambiguation: bool
    similarity: float = 0.0
    score: float = 0.0
    exact_title: bool = False
    from_hint: bool = False  # found only by the second, category-hinted search
    direct_bonus: float = 0.0  # set when the answer itself is this page's title or redirect
    ambiguous: bool = False  # the answer's own title is a disambiguation page
    kind_mismatch: bool = False  # a film, village, name page or record the questions don't ask for
    promoted: bool = False  # ranks first only because a wrong-kind page above it was demoted


# What an article is, from its first sentence, for the kinds that most often get linked by
# mistake: an exact title wins even when the questions ask for something else. "Barabas"
# (Marlowe's Jew of Malta) is a title redirect to Barabás, a village in Hungary; "Wynton" is
# a given-name page; "Richard III" questions about the play matched the 1995 film; battles
# matched the towns they're named for (Poitiers, Chaeronea).
# The kind noun must head the first clause, "X is a [adjectives] NOUN": no "of", "or" or
# "between" before it, or "a poem or song", "a battle between ... the largest single ..."
# and "the name of a fictional planet" would all count.
_FILLER = (
    r"(?:(?!(?:of|or|in|between|about|for|that|which|who|by|from|with|to|on|at|near|"
    r"during|where|whose)\b)[\w'’-]+ ){0,%d}?"
)
_ARTICLE_KINDS = {
    "film": re.compile(
        r"\b(?:is|was) (?:an?|the) " + _FILLER % 6 + r"(?:film|movie)\b"
        r"(?! (?:director|producer|critic|actor|actress|composer|editor|studio|festival|"
        r"score|series))"
    ),
    "settlement": re.compile(
        r"\b(?:is|was) (?:an?|the) " + _FILLER % 5 + r"(?:village|town|commune|municipality|"
        r"hamlet|civil parish|township|census-designated place|city)\b(?!-)"
    ),
    "name": re.compile(
        r"\b(?:is|was) (?:an?|the) " + _FILLER % 3 + r"(?:given name|surname|family name|"
        r"first name|forename)\b|\bpeople with the (?:sur)?name\b"
    ),
    "recording": re.compile(
        r"\b(?:is|was) (?:an?|the) " + _FILLER % 6 + r"(?:studio album|album|single|song|EP)\b"
        r"(?! cycle)"
    ),
}
# Words in a giveaway that ask for that kind of thing: "name this John Schlesinger film",
# "this Spanish city", "give this surname", "give this name, shared by...".
_ASKS_FOR = {
    "film": re.compile(
        r"\b(?:films?|movies?|cinema|directed|director|starring|stars?|starred|screenplay|"
        r"adaptation|animated|remake|live-action|documentary|documentaries)\b"
    ),
    "settlement": re.compile(
        r"\b(?:city|cities|towns?|villages?|capital|commune|municipality|settlement|port|"
        r"metropolis|place|site|location|suburb|borough|hamlet|townsite)\b"
    ),
    "name": re.compile(
        r"\b(?:surnames?|last names?|first names?|given names?|family names?|forenames?|"
        r"famil(?:y|ies)|(?:this|what|these|which) names?|names? shared|shared names?|"
        r"(?:female|male|girl'?s|boy'?s|common|pet|nick) ?names?)\b"
    ),
    "recording": re.compile(
        r"\b(?:albums?|songs?|singles?|records?|tracks?|hits?|ballads?|releases?|tunes?|"
        r"anthems?|singers?|bands?|hymns?|chants?|canticles?|theme|lp|ep)\b"
    ),
}
KIND_PENALTY = 0.2
_SENTENCE_END = re.compile(r"(?<=[a-z0-9)\]\"”])\.\s")


def article_kind(extract: str) -> str | None:
    """The kind of thing an article is about, judged from its first sentence."""
    first = _SENTENCE_END.split(extract.split("\n", 1)[0], maxsplit=1)[0][:300]
    for kind, pattern in _ARTICLE_KINDS.items():
        if pattern.search(first):
            return kind
    return None


def asks_for(kind: str, giveaways: str) -> bool:
    return bool(_ASKS_FOR[kind].search(giveaways))


def search_query(display_name: str, hint: str = "") -> str:
    """Lowercased so "Mercury" and "mercury" share one cached request."""
    return " ".join(_SEARCH_SYNTAX.sub(" ", f"{display_name} {hint}").lower().split())


_HINTS = {
    "Visual Fine Arts": "art",
    "Auditory Fine Arts": "music",
    "Other Fine Arts": "art",
    "Biology": "biology",
    "Chemistry": "chemistry",
    "Physics": "physics",
    "Math": "mathematics",
    "Other Science": "science",
}
_CATEGORY_HINTS = {
    "Literature": "literature",
    "Philosophy": "philosophy",
    "Mythology": "mythology",
    "Religion": "religion",
    "History": "history",
    "Geography": "geography",
    "Social Science": "social science",
}


def search_hint(category: str, subcategory: str) -> str:
    """A word that steers a second search toward the right sense: "The Republic philosophy"."""
    return _HINTS.get(subcategory) or _CATEGORY_HINTS.get(category, "")


def title_lookups(display_name: str) -> list[tuple[str, float]]:
    """Titles to look up for an answer, with the bonus a hit earns.

    "the moon" is also tried as "Moon": quiz answers add "the" freely. The full form earns
    more, so "The Republic" (Plato's book) beats "Republic" when the text agrees.
    """
    title = " ".join(display_name.strip("“”\"' ").split())
    if not title or len(title) > 250 or _BAD_TITLE.search(title):
        return []
    lookups = [(title, 0.35)]
    bare = _ARTICLE.sub("", title)
    if bare != title and bare:
        lookups.append((bare, 0.30))
    return lookups


def parse_title_lookup(response: dict[str, Any]) -> dict[str, Candidate | None]:
    """Maps each requested title to its page (after normalizing and redirects), if any."""
    query = response.get("query") or {}
    normalized = {n["from"]: n["to"] for n in query.get("normalized", [])}
    redirects = {r["from"]: r["to"] for r in query.get("redirects", [])}
    pages = {}
    for page in query.get("pages", []):
        if page.get("missing") or page.get("invalid"):
            continue
        props = page.get("pageprops") or {}
        pages[page["title"]] = Candidate(
            title=page["title"],
            qid=props.get("wikibase_item"),
            extract=page.get("extract", ""),
            rank=0,
            disambiguation="disambiguation" in props,
        )
    out: dict[str, Candidate | None] = {}
    for requested in {*normalized, *redirects, *pages}:
        title = normalized.get(requested, requested)
        title = redirects.get(title, title)
        out[requested] = pages.get(title)
    return out


def parse_candidates(response: dict[str, Any]) -> list[Candidate]:
    pages = (response.get("query") or {}).get("pages") or []
    out = []
    for page in pages:
        props = page.get("pageprops") or {}
        out.append(
            Candidate(
                title=page.get("title", ""),
                qid=props.get("wikibase_item"),
                extract=page.get("extract", ""),
                rank=int(page.get("index", 99)),
                disambiguation="disambiguation" in props,
            )
        )
    return sorted(out, key=lambda c: c.rank)


def score_candidates(
    group_vector: csr_matrix,
    candidates: list[Candidate],
    names: set[str],
    vectorizer: TfidfVectorizer,
    alternates: frozenset[str] = frozenset(),
    giveaways: str | None = None,
) -> list[Candidate]:
    """Scores usable hits in place and returns them best first.

    ``names`` are the group's main answers; ``alternates`` its accepted forms, which earn a
    smaller bonus because answer lines often accept narrower things ("the rabbit in the moon").
    ``giveaways`` is the lowercased text of the questions' giveaways: a film, village, name
    page or record they never ask for loses ``KIND_PENALTY`` (see ``article_kind``).
    """
    usable = [c for c in candidates if c.qid and not c.disambiguation]
    if not usable:
        return []
    vectors = vectorizer.transform([f"{c.title}. {c.extract}" for c in usable])
    sims = (vectors @ group_vector.T).toarray().ravel()
    for cand, sim in zip(usable, sims, strict=True):
        title = normalize(_PAREN.sub("", cand.title), singularize=True)
        cand.exact_title = title in names or cand.direct_bonus > 0
        if cand.direct_bonus:
            bonus = cand.direct_bonus
        elif cand.exact_title:
            # A plain title ("Snake", not "Snake (zodiac)") is Wikipedia's main article.
            bonus = 0.25 if "(" in cand.title else 0.30
        elif title in alternates or any(len(n) > 3 and (n in title or title in n) for n in names):
            bonus = 0.12
        else:
            bonus = 0.0
        cand.similarity = float(sim)
        penalty = 0.05 if cand.from_hint else 0.0
        kind = article_kind(cand.extract) if giveaways is not None else None
        cand.kind_mismatch = kind is not None and not asks_for(kind, giveaways or "")
        if cand.kind_mismatch:
            penalty += KIND_PENALTY
        cand.promoted = False
        cand.score = float(sim) + bonus - penalty + 0.01 * max(0, 5 - cand.rank)
    ranked = sorted(usable, key=lambda c: -c.score)
    unpenalized = max(usable, key=lambda c: c.score + KIND_PENALTY * c.kind_mismatch)
    if unpenalized.kind_mismatch and unpenalized is not ranked[0]:
        winner = ranked[0]
        if not (winner.exact_title or winner.direct_bonus):
            # The demotion may move a link only to a page titled for the answer (the play
            # "Desire Under the Elms", not the film): a partial match winning by default is
            # as often wrong as right ("Michael" -> Michael Jackson, but "The Dreamtime" ->
            # The Dreaming). Then nothing changes: the original order stands.
            for cand in usable:
                cand.score += KIND_PENALTY * cand.kind_mismatch
            return sorted(usable, key=lambda c: -c.score)
        winner.promoted = True
    return ranked


def giveaway_text(question: str) -> str:
    """The question's giveaway: where it says what kind of answer it wants."""
    layout = split_question(question)
    return " ".join(c.text for c in layout.clues if c.kind == "giveaway")


def make_client(settings: PipelineSettings, user_agent: str) -> WikiClient:
    return WikiClient(HttpCache(settings.http_cache_dir / "wikimedia.db"), user_agent)


def accept_link(best: Candidate, settings: PipelineSettings) -> bool:
    """An exact title match needs far less text overlap: "France" asked in music questions.

    An exact match on Wikipedia's main article (no parenthetical) needs none: a single stray
    question ("Napoleon Bonaparte" in a literature set) gives too little text to compare.
    """
    if best.kind_mismatch:
        # A title match proves nothing when the page is the wrong kind of thing: the text
        # has to agree on its own.
        needed = settings.link_min_similarity
    elif best.ambiguous:
        # "Doctor", "Bliss", "The Republic" are disambiguation pages: the name alone proves
        # nothing, so the page has to agree with the questions.
        needed = settings.link_min_similarity
    elif best.direct_bonus:
        needed = 0.0  # the answer is literally this page's title or a redirect to it
    elif best.exact_title:
        needed = 0.0 if "(" not in best.title else settings.link_min_similarity / 5
    else:
        needed = settings.link_min_similarity
    return best.score >= settings.link_min_score and best.similarity >= needed


class TitleStore:
    """Direct title lookups kept per title across runs.

    Lookups are batched 20 to a request, and the HTTP cache is keyed by the whole batch, so
    renaming a few answers would shift every batch and refetch everything. Storing results
    per title means only titles never seen before are requested.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS titles (requested TEXT PRIMARY KEY, page TEXT)"
        )
        self._pages: dict[str, str | None] = dict(self.conn.execute("SELECT * FROM titles"))

    def __contains__(self, title: str) -> bool:
        return title in self._pages

    def get(self, title: str) -> Candidate | None:
        page = self._pages.get(title)
        return Candidate(**json.loads(page)) if page else None

    def put_batch(self, requested: list[str], found: dict[str, Candidate | None]) -> None:
        rows = []
        for title in requested:
            hit = found.get(title)
            rows.append((title, json.dumps(asdict(hit)) if hit else None))
        self.conn.executemany("INSERT OR REPLACE INTO titles VALUES (?, ?)", rows)
        self.conn.commit()
        self._pages.update(rows)

    def seed_from(self, cache: HttpCache) -> None:
        """Fills the store once from title-lookup batches already in the HTTP cache."""
        if self._pages:
            return
        for key, body in cache.conn.execute(
            "SELECT key, body FROM responses WHERE key LIKE '%titles=%'"
        ):
            requested = parse_qs(urlsplit(key).query).get("titles", [""])[0].split("|")
            self.put_batch(requested, parse_title_lookup(json.loads(gzip.decompress(body))))


def merge_direct(
    candidates: list[Candidate], display: str, direct: dict[str, Candidate | None]
) -> list[Candidate]:
    """Adds direct title hits to the search results, marking any already there.

    If the answer's own title is a disambiguation page, every candidate is marked ambiguous
    and the bare form ("Republic" for "The Republic") isn't treated as a direct hit.
    """
    lookups = title_lookups(display)
    full = direct.get(lookups[0][0]) if lookups else None
    ambiguous = full is not None and full.disambiguation
    by_title = {c.title: c for c in candidates}
    for lookup, bonus in lookups:
        hit = direct.get(lookup)
        if ambiguous or hit is None or hit.disambiguation or not hit.qid:
            continue
        target = by_title.get(hit.title)
        if target is None:
            target = Candidate(hit.title, hit.qid, hit.extract, 0, False)
            by_title[hit.title] = target
            candidates = [*candidates, target]
        target.direct_bonus = max(target.direct_bonus, bonus)
    for cand in candidates:
        cand.ambiguous = ambiguous
    return candidates


def needs_second_search(scored: list[Candidate], n_tossups: int) -> bool:
    return n_tossups >= 2 and (not scored or scored[0].similarity < 0.08)


def run(settings: PipelineSettings, reporter: Reporter) -> None:
    user_agent = settings.require_wikimedia_contact()
    conn = db.connect(settings.corpus_path)
    db.require_table(conn, "candidate_groups", "group")
    db.recreate(conn, SCHEMA)

    reporter.begin("Learning vocabulary from all questions", None)
    tossup_ids, texts = zip(*conn.execute("SELECT id, question_text FROM tossups"), strict=True)
    big = len(texts) > 1000  # rare-word filtering only makes sense on the real corpus
    vectorizer = TfidfVectorizer(
        stop_words="english",
        sublinear_tf=True,
        min_df=2 if big else 1,
        max_df=0.5 if big else 1.0,
        dtype=np.float32,
    )
    matrix = vectorizer.fit_transform(texts)
    row_of = {tid: i for i, tid in enumerate(tossup_ids)}

    question_text = dict(zip(tossup_ids, texts, strict=True))
    members: dict[int, list[int]] = defaultdict(list)
    giveaways: dict[int, list[str]] = defaultdict(list)
    names: dict[int, set[str]] = defaultdict(set)
    alternates: dict[int, set[str]] = defaultdict(set)
    for group_id, tossup_id, main_norm, accept, required in conn.execute(
        "SELECT g.group_id, g.tossup_id, a.main_norm, a.accept, a.required "
        "FROM tossup_groups g JOIN answer_parses a ON a.tossup_id = g.tossup_id"
    ):
        members[group_id].append(row_of[tossup_id])
        giveaways[group_id].append(giveaway_text(question_text[tossup_id]))
        names[group_id].add(main_norm)
        alternates[group_id].update(
            normalize(a["text"], singularize=True) for a in json.loads(accept)
        )
        alternates[group_id].update(normalize(r, singularize=True) for r in json.loads(required))

    groups = conn.execute(
        "SELECT id, display_name, n_tossups, category, subcategory "
        "FROM candidate_groups ORDER BY n_tossups DESC, id"
    ).fetchall()
    client = make_client(settings, user_agent)

    def allowed(params: dict[str, Any]) -> bool:
        return (
            settings.link_new_requests is None
            or client.network_requests < settings.link_new_requests
            or client.is_cached(WIKIPEDIA_API, params)
        )

    # Pass 1: every answer as a direct title lookup, batched.
    wanted = sorted(
        {
            title
            for _gid, display, n, _c, _s in groups
            if n >= settings.link_min_tossups
            for title, _bonus in title_lookups(display)
        }
    )
    store = TitleStore(settings.http_cache_dir / "wikipedia_titles.db")
    store.seed_from(client.cache)
    missing = [t for t in wanted if t not in store]
    batches = [missing[i : i + TITLE_BATCH] for i in range(0, len(missing), TITLE_BATCH)]
    reporter.begin("Looking up answers as Wikipedia titles", len(batches))
    for batch in batches:
        params = titles_params(batch)
        if allowed(params):
            store.put_batch(batch, parse_title_lookup(client.get_json(WIKIPEDIA_API, params)))
        reporter.advance()
    direct = {t: store.get(t) for t in wanted if t in store}
    reporter.stat("Answers that are Wikipedia titles", f"{sum(1 for c in direct.values() if c):,}")

    # Pass 2: search and score, group by group.
    reporter.begin("Linking to Wikipedia", len(groups))
    counts = {"linked": 0, "no_match": 0, "skipped": 0}

    for i, (group_id, display, n_tossups, category, subcategory) in enumerate(groups, start=1):
        params = search_params(search_query(display))
        if (
            n_tossups < settings.link_min_tossups
            or not search_query(display)
            or not allowed(params)
        ):
            status, best, scored = "skipped", None, []
        else:
            vector = l2_normalize(csr_matrix(matrix[members[group_id]].sum(axis=0)))
            candidates = parse_candidates(client.get_json(WIKIPEDIA_API, params))
            candidates = merge_direct(candidates, display, direct)
            asked = " ".join(giveaways[group_id]).lower()
            scored = score_candidates(
                vector,
                candidates,
                names[group_id],
                vectorizer,
                frozenset(alternates[group_id]),
                asked,
            )
            hint = search_hint(category, subcategory)
            if hint and needs_second_search(scored, n_tossups):
                params2 = search_params(search_query(display, hint))
                if allowed(params2):
                    seen = {c.title for c in candidates}
                    extra = parse_candidates(client.get_json(WIKIPEDIA_API, params2))
                    for c in extra:
                        c.from_hint = True
                        c.ambiguous = bool(candidates and candidates[0].ambiguous)
                    candidates += [c for c in extra if c.title not in seen]
                    scored = score_candidates(
                        vector,
                        candidates,
                        names[group_id],
                        vectorizer,
                        frozenset(alternates[group_id]),
                        asked,
                    )
            best = scored[0] if scored and accept_link(scored[0], settings) else None
            status = "linked" if best else "no_match"
        counts[status] += 1
        conn.execute(
            "INSERT INTO group_links VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                group_id,
                status,
                best.qid if best else None,
                best.title if best else None,
                best.score if best else None,
                best.similarity if best else None,
                json.dumps(
                    [{k: v for k, v in asdict(c).items() if k != "extract"} for c in scored[:5]]
                ),
            ),
        )
        reporter.advance()
        if i % 200 == 0:
            conn.commit()
            reporter.stat(
                "Linked / no match / skipped", " / ".join(f"{v:,}" for v in counts.values())
            )
            reporter.stat("New web requests", f"{client.network_requests:,}")
    conn.commit()
    reporter.stat("Linked / no match / skipped", " / ".join(f"{v:,}" for v in counts.values()))
    reporter.stat("New web requests", f"{client.network_requests:,}")

    topics.build(conn, reporter)
    conn.close()
