"""Stage 8: find related topics: topics named inside another topic's questions.

Every clue and giveaway is scanned for other topics' names. A hit means "topic A's
question mentions topic B" ("... FIFA ..." in a soccer question), and the clue that
caused it is kept so the page can say *why* the two are related.

Which names are searched for: main answers, Wikipedia titles and Wikidata aliases, plus
accepted and required answer parts seen in more than one answer line ("What We Think" is
accepted for soccer once; "main characters" is required once for *Midnight's Children*).
Each name is at least 4 characters, not just a number ("1984" is a novel *and* a year),
doesn't start with an article, and doesn't end in a stopword or a stray "s" ("existence
of", "river's"). A lowercase name found in more than ``relate_max_alias_topics`` topics'
questions is a generic phrase, not a name ("18th century", "first movement"), and is
dropped.

A multi-word name shared by several topics is resolved by the question's category:
"Battle Royale" in a literature question is the battle royal in *Invisible Man*, not the
Japanese film. If several owners share the category, the one whose own name it is wins
("Calvin cycle", which photosynthesis also accepts). If none does, the topic whose
Wikipedia title it is wins; if it's still unclear, the name is skipped.

A shared one-word name is riskier: the owner in the question's category gets it only if
it's that topic's own name ("the Brotherhood" in *Invisible Man*), not a side alias
("Columbia" claimed by the space shuttle in a biology question); otherwise only an
all-caps title owner keeps it ("FIFA", also a minor alias of a FIFA tournament).

Names are strong or weak:

* strong: an all-caps one-word title ("FIFA"); the topic's own lowercase name ("Calvin
  cycle"); any capitalized multi-word alias ("Soccer World Cup");
* weak: other one-word names ("Bledsoe" is also an NFL quarterback; "Pele" is the title
  of the goddess, and the footballer has no topic) and lowercase extras ("black man" for
  Black people). A weak name counts only when both topics share a category, so "PEP
  carboxylase" still links photosynthesis.

How a name must appear in the clue:

* a capitalized name must be capitalized there too ("What is your name?" doesn't name
  the film *Your Name*), and mustn't be part of a longer name ("Dr. Bledsoe", "Alfred
  Sturtevant", "Ten Years Later");
* a one-word name must be a proper noun: capitalized in most of its mid-sentence uses
  across the corpus. That keeps "Hox" and drops "water" and "power".

Matching is longest-first, so "FIFA World Cup" isn't also counted as "World Cup".

Edges are scored per pair:

    score(A, B) = log(1 + questions of A naming B) * idf(B)
                  + reverse_weight * log(1 + questions of B naming A) * idf(A)

where idf(X) = log(topics / topics whose questions name X). A topic named everywhere
("France", "World War II") says little about any one topic, so it's discounted, and such a
hub (named in more than ``relate_hub_topics`` topics' questions) must also earn its place:
it has to appear in at least 3 of the topic's questions and a quarter of them ("American"
in two questions of a novel isn't a relation; France in a third of Napoleon's is). Each
topic keeps its top ``relate_top`` edges with at least ``relate_min_questions`` questions of
support.
"""

import math
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

from unidecode import unidecode

from hortum_pipeline import db
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import Reporter

SCHEMA = """
DROP TABLE IF EXISTS related_topics;
DROP TABLE IF EXISTS clue_mentions;
CREATE TABLE clue_mentions (
    clue_id INTEGER NOT NULL REFERENCES clues(id),
    topic_id TEXT NOT NULL REFERENCES topics(id),           -- the question's topic (A)
    mentioned_topic_id TEXT NOT NULL REFERENCES topics(id), -- the topic named (B)
    alias TEXT NOT NULL,                                    -- alias_search that matched
    char_start INTEGER NOT NULL,                            -- span within the clue text
    char_end INTEGER NOT NULL
);
CREATE INDEX clue_mentions_clue ON clue_mentions(clue_id);
CREATE INDEX clue_mentions_pair ON clue_mentions(topic_id, mentioned_topic_id);
CREATE TABLE related_topics (
    topic_id TEXT NOT NULL REFERENCES topics(id),
    related_topic_id TEXT NOT NULL REFERENCES topics(id),
    rank INTEGER NOT NULL,
    score REAL NOT NULL,
    n_questions INTEGER NOT NULL,     -- questions about topic_id that name related_topic_id
    n_reverse INTEGER NOT NULL,       -- questions about related_topic_id that name topic_id
    example_clue_id INTEGER NOT NULL REFERENCES clues(id),
    PRIMARY KEY (topic_id, related_topic_id)
);
"""

_WORD = re.compile(r"\w+|&")
_NON_WORD = re.compile(r"[^a-z0-9]+")
_MAX_ALIAS_TOKENS = 8
_STOPWORD_TEXT = """
a an and are as at be but by for from has have he her his i if in into is it its me my no
not of on or our she so that the their them they this to us was we were what when where
which who why will with you your all one two new old
"""
STOPWORDS = frozenset(_STOPWORD_TEXT.split())
# A name can't end in a function word ("existence of"); "I" and "A" end real names
# ("World War I", "Vitamin A").
_TRAILING_TEXT = "of the and to in for with by from at on as or an is are was were be"
_TRAILING = frozenset(_TRAILING_TEXT.split())


@dataclass(frozen=True)
class Token:
    key: str  # lowercase ASCII, as in topic_aliases.alias_search
    start: int
    end: int
    capitalized: bool


def tokenize(text: str) -> list[Token]:
    """Words of ``text`` keyed like ``normalize`` keys aliases, with character spans."""
    out = []
    for match in _WORD.finditer(text):
        raw = match.group()
        if raw == "&":
            out.append(Token("and", match.start(), match.end(), False))
            continue
        folded = _NON_WORD.sub(" ", unidecode(unicodedata.normalize("NFKC", raw)).lower())
        for part in folded.split():
            out.append(Token(part, match.start(), match.end(), raw[:1].isupper()))
    return out


def usable_alias(alias_search: str) -> bool:
    tokens = alias_search.split()
    return (
        len(alias_search) >= 4
        and not alias_search.replace(" ", "").isdigit()
        and tokens[0] not in ("a", "an", "the")
        and tokens[-1] not in _TRAILING
        and tokens[-1] != "s"
        and len(tokens) <= _MAX_ALIAS_TOKENS
    )


def is_proper(alias: str) -> bool:
    """Every content word capitalized ("Your Name", "FIFA World Cup"), as a name is written."""
    words = [w for w in _WORD.findall(alias) if w.lower() not in STOPWORDS and w != "&"]
    return bool(words) and all(w[:1].isupper() or w[:1].isdigit() for w in words)


def capitalized_share(texts: Iterator[str]) -> dict[str, float]:
    """For each word, the share of its mid-sentence uses that are capitalized."""
    seen: Counter[str] = Counter()
    upper: Counter[str] = Counter()
    for text in texts:
        for token in tokenize(text)[1:]:  # the first word is capitalized anyway
            seen[token.key] += 1
            upper[token.key] += token.capitalized
    return {w: upper[w] / seen[w] for w in seen}


@dataclass(frozen=True)
class Alias:
    topic_id: str
    category: str | None
    proper: bool  # written capitalized, so it must appear capitalized
    weak: bool  # counts only when both topics share a category
    single: bool
    title: bool = False  # the topic's Wikipedia title
    own_name: bool = False  # the topic's title or main answer, not a side alias
    usable: bool = True  # False: the owner only claims it as a rare or rejected answer


class AliasMatcher:
    """Longest-first matching of alias token sequences, with the rules above."""

    def __init__(self, aliases: dict[str, list[Alias]], name_like: set[str]) -> None:
        self.aliases = aliases  # alias_search -> one Alias per topic that claims it
        self.name_like = name_like  # words usually capitalized mid-sentence
        self.prefixes = {
            " ".join(a.split()[:n]) for a in aliases for n in range(1, len(a.split()) + 1)
        }

    @staticmethod
    def choose(owners: list[Alias], category: str | None) -> Alias | None:
        """Which topic a name means in a question of ``category``, if any."""
        if len(owners) == 1:
            return owners[0] if owners[0].usable else None
        local = [o for o in owners if o.category == category]
        if len(local) > 1:
            # Photosynthesis accepts "Calvin Cycle", but it's the Calvin cycle's own title.
            local = [o for o in local if o.own_name] or local
        if owners[0].single:
            # One word settles by category only when it's that topic's own name ("the
            # Brotherhood" in Invisible Man), not a side alias ("Columbia" for the space
            # shuttle); otherwise only an all-caps title owner ("FIFA") keeps it.
            if len(local) == 1 and local[0].own_name and local[0].usable:
                return local[0]
            strong = [o for o in owners if o.usable and not o.weak]
            return strong[0] if len(strong) == 1 else None
        if len(local) == 1:
            return local[0] if local[0].usable else None
        if local:
            return None
        titled = [o for o in owners if o.title and o.usable and not o.weak]
        return titled[0] if len(titled) == 1 else None

    def _fits(
        self, alias: Alias, tokens: list[Token], i: int, j: int, category: str | None
    ) -> bool:
        span = tokens[i : j + 1]
        if alias.proper and not all(t.capitalized for t in span if t.key not in STOPWORDS):
            return False
        if alias.weak and alias.category != category:
            return False
        if alias.proper:
            for k in (i - 1, j + 1):
                neighbor = tokens[k] if 0 <= k < len(tokens) else None
                if (
                    neighbor
                    and neighbor.capitalized
                    and neighbor.key not in STOPWORDS
                    and (k > 0 or neighbor.key in self.name_like)
                ):
                    return False  # part of a longer name
        return True

    def find(
        self, tokens: list[Token], category: str | None = None
    ) -> list[tuple[str, str, int, int]]:
        """(alias, topic id, char start, char end) for each hit, left to right."""
        hits = []
        i = 0
        while i < len(tokens):
            found = []
            key = ""
            for j in range(i, min(i + _MAX_ALIAS_TOKENS, len(tokens))):
                key = f"{key} {tokens[j].key}" if key else tokens[j].key
                if key not in self.prefixes:
                    break
                if key in self.aliases:
                    found.append((key, j))
            for key, j in reversed(found):  # longest first
                alias = self.choose(self.aliases[key], category)
                if alias and self._fits(alias, tokens, i, j, category):
                    hits.append((key, alias.topic_id, tokens[i].start, tokens[j].end))
                    i = j
                    break
            i += 1
        return hits


_NAME_SOURCES = ("title", "main")
_ANSWER_SOURCES = ("accept", "required")  # from answer lines: trusted once seen twice


def load_aliases(
    conn: sqlite3.Connection, share: dict[str, float], min_cap_share: float
) -> dict[str, list[Alias]]:
    rows: dict[str, dict[str, list[tuple[float, str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for topic_id, alias, alias_search, source, weight in conn.execute(
        "SELECT topic_id, alias, alias_search, source, weight FROM topic_aliases"
    ):
        rows[alias_search][topic_id].append((weight, alias, source))
    categories = dict(conn.execute("SELECT id, primary_category FROM topics"))
    out: dict[str, list[Alias]] = {}
    for alias_search, by_owner in rows.items():
        if not usable_alias(alias_search):
            continue
        single = " " not in alias_search
        if single and share.get(alias_search, 0.0) < min_cap_share:
            continue
        owners = []
        for topic_id, all_rows in by_owner.items():
            found = [r for r in all_rows if r[2] not in _ANSWER_SOURCES or r[0] >= 1.0]
            names = sorted((r for r in found if r[2] in _NAME_SOURCES), reverse=True)
            form = names[0][1] if names else max(found or all_rows)[1]
            proper = single or is_proper(form)
            # A one-word name is strong only as an all-caps title ("FIFA", "NATO").
            acronym_title = any(r[2] == "title" and r[1].isupper() for r in found)
            weak = not acronym_title if single else not names and not proper
            owners.append(
                Alias(
                    topic_id,
                    categories.get(topic_id),
                    proper,
                    weak,
                    single,
                    title=any(r[2] == "title" for r in found),
                    own_name=bool(names),
                    usable=bool(found),
                )
            )
        if any(o.usable for o in owners):
            out[alias_search] = owners
    return out


def score_edges(
    forward: dict[tuple[str, str], set[str]],
    n_topics: int,
    reverse_weight: float,
) -> dict[tuple[str, str], tuple[float, int, int]]:
    """(A, B) -> (score, questions of A naming B, questions of B naming A)."""
    df: Counter[str] = Counter(b for _, b in forward)
    idf = {b: math.log(n_topics / n) for b, n in df.items()}
    out = {}
    for a, b in set(forward) | {(b, a) for a, b in forward}:
        fwd = len(forward.get((a, b), ()))
        rev = len(forward.get((b, a), ()))
        value = math.log1p(fwd) * idf.get(b, 0.0) + reverse_weight * math.log1p(rev) * idf.get(
            a, 0.0
        )
        out[(a, b)] = (value, fwd, rev)
    return out


def is_strong_hub_link(questions_naming: int, topic_questions: int) -> bool:
    """A hub topic ("France") is related only if it's in 3+ and a quarter of the questions."""
    return questions_naming >= 3 and questions_naming >= 0.25 * topic_questions


def run(settings: PipelineSettings, reporter: Reporter) -> None:
    conn = db.connect(settings.corpus_path)
    db.require_table(conn, "cluster_scores", "score")
    db.recreate(conn, SCHEMA)

    query = (
        "SELECT c.id, c.topic_id, c.tossup_id, c.text, c.kind, COALESCE(k.n_sets, 0) "
        "FROM clues c LEFT JOIN clue_cluster_members m ON m.clue_id = c.id "
        "LEFT JOIN clue_clusters k ON k.id = m.cluster_id "
        "WHERE c.kind != 'note' AND c.topic_id IS NOT NULL"
    )
    n_clues = conn.execute(
        "SELECT COUNT(*) FROM clues WHERE kind != 'note' AND topic_id IS NOT NULL"
    ).fetchone()[0]

    reporter.begin("Choosing names to search for", None)
    share = capitalized_share(
        r[0] for r in conn.execute("SELECT text FROM clues WHERE kind != 'note'")
    )
    aliases = load_aliases(conn, share, settings.relate_min_cap_share)
    reporter.stat("Names searched for", f"{len(aliases):,}")
    name_like = {w for w, v in share.items() if v >= settings.relate_min_cap_share}
    matcher = AliasMatcher(aliases, name_like)
    categories = dict(conn.execute("SELECT id, primary_category FROM topics"))

    reporter.begin("Scanning clues for other topics", n_clues)
    hits: list[tuple[int, str, str, str, str, int, int, str, int]] = []
    scanned = 0
    for clue_id, topic_id, tossup_id, text, kind, n_sets in conn.execute(query):
        for alias, other, start, end in matcher.find(tokenize(text), categories.get(topic_id)):
            if other != topic_id:
                hits.append((clue_id, topic_id, tossup_id, other, alias, start, end, kind, n_sets))
        scanned += 1
        if scanned % 5_000 == 0:
            reporter.advance(5_000)
    reporter.advance(scanned % 5_000)

    alias_topics: dict[str, set[str]] = defaultdict(set)
    for hit in hits:
        alias_topics[hit[4]].add(hit[1])
    generic = {
        a
        for a, topics in alias_topics.items()
        if not any(o.proper for o in aliases[a]) and len(topics) > settings.relate_max_alias_topics
    }
    reporter.stat("Generic phrases dropped", ", ".join(sorted(generic)[:8]) or "none")

    forward: dict[tuple[str, str], set[str]] = defaultdict(set)
    # Best example per pair: real clues first, then the most commonly asked, then earliest.
    example: dict[tuple[str, str], tuple[tuple[bool, int, int], int]] = {}
    mentions = []
    for clue_id, topic_id, tossup_id, other, alias, start, end, kind, n_sets in hits:
        if alias in generic:
            continue
        pair = (topic_id, other)
        forward[pair].add(tossup_id)
        mentions.append((clue_id, topic_id, other, alias, start, end))
        rank_key = (kind != "clue", -n_sets, clue_id)
        if pair not in example or rank_key < example[pair][0]:
            example[pair] = (rank_key, clue_id)
    conn.executemany("INSERT INTO clue_mentions VALUES (?, ?, ?, ?, ?, ?)", mentions)

    reporter.begin("Ranking related topics", None)
    sizes = dict(conn.execute("SELECT id, n_tossups FROM topics"))
    n_topics = conn.execute("SELECT COUNT(DISTINCT topic_id) FROM clues").fetchone()[0]
    edges = score_edges(forward, max(n_topics, 2), settings.relate_reverse_weight)
    reach = Counter(b for _, b in forward)
    by_topic: dict[str, list[tuple[float, str, int, int]]] = defaultdict(list)
    for (a, b), (value, fwd, rev) in edges.items():
        need = settings.relate_min_questions if sizes.get(a, 0) >= 6 else 1
        if fwd + rev < need:
            continue
        if reach[b] > settings.relate_hub_topics and not is_strong_hub_link(fwd, sizes.get(a, 0)):
            continue
        by_topic[a].append((value, b, fwd, rev))
    rows = []
    for a, candidates in by_topic.items():
        candidates.sort(key=lambda c: (-c[0], c[1]))
        for rank, (value, b, fwd, rev) in enumerate(candidates[: settings.relate_top], start=1):
            clue = example[(a, b)][1] if (a, b) in example else example[(b, a)][1]
            rows.append((a, b, rank, round(value, 4), fwd, rev, clue))
    conn.executemany("INSERT INTO related_topics VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()

    n_mentions = conn.execute("SELECT COUNT(*) FROM clue_mentions").fetchone()[0]
    reporter.stat("Mentions of other topics", f"{n_mentions:,}")
    reporter.stat("Topics with related topics", f"{len(by_topic):,} of {len(sizes):,}")
    reporter.stat("Related-topic links kept", f"{len(rows):,}")
    conn.close()
