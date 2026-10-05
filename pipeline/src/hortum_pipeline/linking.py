"""Stage 4: link candidate groups to Wikipedia/Wikidata, then build topics.

For each group, one Wikipedia request returns the top search hits with their intro
text and Wikidata ID. Each hit is scored by TF-IDF similarity between its intro and
the group's own questions, plus bonuses when its title matches the answer. Groups that
resolve to the same Wikidata item merge into one topic.
"""

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize as l2_normalize

from hortum_common.text import normalize
from hortum_pipeline import db, topics
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import Reporter
from hortum_pipeline.wiki import WIKIPEDIA_API, HttpCache, WikiClient, search_params

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
) -> list[Candidate]:
    """Scores usable hits in place and returns them best first.

    ``names`` are the group's main answers; ``alternates`` its accepted forms, which earn a
    smaller bonus because answer lines often accept narrower things ("the rabbit in the moon").
    """
    usable = [c for c in candidates if c.qid and not c.disambiguation]
    if not usable:
        return []
    vectors = vectorizer.transform([f"{c.title}. {c.extract}" for c in usable])
    sims = (vectors @ group_vector.T).toarray().ravel()
    for cand, sim in zip(usable, sims, strict=True):
        title = normalize(_PAREN.sub("", cand.title), singularize=True)
        cand.exact_title = title in names
        if cand.exact_title:
            # A plain title ("Snake", not "Snake (zodiac)") is Wikipedia's main article.
            bonus = 0.25 if "(" in cand.title else 0.30
        elif title in alternates or any(len(n) > 3 and (n in title or title in n) for n in names):
            bonus = 0.12
        else:
            bonus = 0.0
        cand.similarity = float(sim)
        penalty = 0.05 if cand.from_hint else 0.0
        cand.score = float(sim) + bonus - penalty + 0.01 * max(0, 5 - cand.rank)
    return sorted(usable, key=lambda c: -c.score)


def make_client(settings: PipelineSettings, user_agent: str) -> WikiClient:
    return WikiClient(HttpCache(settings.http_cache_dir / "wikimedia.db"), user_agent)


def accept_link(best: Candidate, settings: PipelineSettings) -> bool:
    """An exact title match needs far less text overlap: "France" asked in music questions.

    An exact match on Wikipedia's main article (no parenthetical) needs none: a single stray
    question ("Napoleon Bonaparte" in a literature set) gives too little text to compare.
    """
    if best.exact_title:
        needed = 0.0 if "(" not in best.title else settings.link_min_similarity / 5
    else:
        needed = settings.link_min_similarity
    return best.score >= settings.link_min_score and best.similarity >= needed


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

    members: dict[int, list[int]] = defaultdict(list)
    names: dict[int, set[str]] = defaultdict(set)
    alternates: dict[int, set[str]] = defaultdict(set)
    for group_id, tossup_id, main_norm, accept, required in conn.execute(
        "SELECT g.group_id, g.tossup_id, a.main_norm, a.accept, a.required "
        "FROM tossup_groups g JOIN answer_parses a ON a.tossup_id = g.tossup_id"
    ):
        members[group_id].append(row_of[tossup_id])
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
    reporter.begin("Linking to Wikipedia", len(groups))
    counts = {"linked": 0, "no_match": 0, "skipped": 0}

    def allowed(params: dict[str, Any]) -> bool:
        return (
            settings.link_new_requests is None
            or client.network_requests < settings.link_new_requests
            or client.is_cached(WIKIPEDIA_API, params)
        )

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
            scored = score_candidates(
                vector, candidates, names[group_id], vectorizer, frozenset(alternates[group_id])
            )
            hint = search_hint(category, subcategory)
            if hint and needs_second_search(scored, n_tossups):
                params2 = search_params(search_query(display, hint))
                if allowed(params2):
                    seen = {c.title for c in candidates}
                    extra = parse_candidates(client.get_json(WIKIPEDIA_API, params2))
                    for c in extra:
                        c.from_hint = True
                    candidates += [c for c in extra if c.title not in seen]
                    scored = score_candidates(
                        vector,
                        candidates,
                        names[group_id],
                        vectorizer,
                        frozenset(alternates[group_id]),
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
