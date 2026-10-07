"""Stage 4b: dates, places, descriptions and aliases from Wikidata (via SPARQL).

SPARQL returns only the properties we need, which keeps responses small; fetching full
entities would download megabytes of claims for items like countries.
"""

import json
import re
import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import httpx

from hortum_common.text import normalize
from hortum_pipeline import db, topics
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import Reporter
from hortum_pipeline.wiki import WIKIDATA_SPARQL, HttpCache, NotCached, WikiClient, sparql_params

SCHEMA = """
DROP TABLE IF EXISTS topic_facts;
CREATE TABLE topic_facts (
    topic_id TEXT NOT NULL REFERENCES topics(id),
    kind TEXT NOT NULL,       -- date | place
    property TEXT NOT NULL,   -- Wikidata property, e.g. P585
    value TEXT NOT NULL       -- JSON: {time, precision} | {lat, lon, label, place}
);
CREATE INDEX topic_facts_topic ON topic_facts(topic_id);
"""

DATE_PROPERTIES = {
    "P585": "point in time",
    "P580": "start time",
    "P582": "end time",
    "P571": "inception",
    "P576": "dissolved",
    "P569": "date of birth",
    "P570": "date of death",
    "P577": "publication date",
}
PLACE_PROPERTIES = {
    "P276": "location",
    "P19": "place of birth",
    "P20": "place of death",
    "P131": "located in",
    "P17": "country",
}
BATCH = 50

_POINT = re.compile(r"Point\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)")


def _values(qids: Sequence[str]) -> str:
    return " ".join(f"wd:{q}" for q in qids)


def labels_query(qids: Sequence[str]) -> str:
    return f"""
    SELECT ?item ?desc ?alias WHERE {{
      VALUES ?item {{ {_values(qids)} }}
      OPTIONAL {{ ?item schema:description ?desc FILTER(LANG(?desc) = "en") }}
      OPTIONAL {{ ?item skos:altLabel ?alias FILTER(LANG(?alias) = "en") }}
    }}"""


def dates_query(qids: Sequence[str]) -> str:
    props = " ".join(f'("{p}" p:{p} psv:{p})' for p in DATE_PROPERTIES)
    return f"""
    SELECT ?item ?prop ?time ?precision WHERE {{
      VALUES ?item {{ {_values(qids)} }}
      VALUES (?prop ?p ?psv) {{ {props} }}
      ?item ?p ?st . ?st ?psv ?node .
      ?node wikibase:timeValue ?time ; wikibase:timePrecision ?precision .
      FILTER NOT EXISTS {{ ?st wikibase:rank wikibase:DeprecatedRank }}
    }}"""


def places_query(qids: Sequence[str]) -> str:
    props = " ".join(f'("{p}" wdt:{p})' for p in PLACE_PROPERTIES)
    return f"""
    SELECT ?item ?prop ?place ?placeLabel ?coord WHERE {{
      VALUES ?item {{ {_values(qids)} }}
      {{ ?item wdt:P625 ?coord . BIND("P625" AS ?prop) }}
      UNION
      {{ VALUES (?prop ?wdt) {{ {props} }}
         ?item ?wdt ?place . ?place wdt:P625 ?coord .
         OPTIONAL {{ ?place rdfs:label ?placeLabel FILTER(LANG(?placeLabel) = "en") }} }}
    }}"""


def _bindings(response: dict[str, Any]) -> Iterator[dict[str, str]]:
    for row in response.get("results", {}).get("bindings", []):
        yield {key: cell["value"] for key, cell in row.items()}


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def parse_labels(response: dict[str, Any]) -> tuple[dict[str, str], dict[str, set[str]]]:
    descriptions: dict[str, str] = {}
    aliases: dict[str, set[str]] = {}
    for row in _bindings(response):
        qid = _qid(row["item"])
        if "desc" in row:
            descriptions[qid] = row["desc"]
        if "alias" in row:
            aliases.setdefault(qid, set()).add(row["alias"])
    return descriptions, aliases


def parse_dates(response: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    out = []
    for row in _bindings(response):
        value = {"time": row["time"], "precision": int(row["precision"])}
        out.append((_qid(row["item"]), row["prop"], value))
    return out


def parse_places(response: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    out = []
    for row in _bindings(response):
        match = _POINT.match(row.get("coord", ""))
        if not match:
            continue  # coordinates on other globes (the Moon, Mars) come as different literals
        value: dict[str, Any] = {"lon": float(match.group(1)), "lat": float(match.group(2))}
        if "place" in row:
            value["place"] = _qid(row["place"])
            value["label"] = row.get("placeLabel", "")
        out.append((_qid(row["item"]), row["prop"], value))
    return out


def make_client(settings: PipelineSettings, user_agent: str) -> WikiClient:
    # The query service is shared and expensive; one query a second is plenty.
    # Queries can take a while server-side (the service's own limit is 60s).
    return WikiClient(
        HttpCache(settings.http_cache_dir / "wikidata.db"),
        user_agent,
        min_interval=1.0,
        timeout=90.0,
    )


class FactsStore:
    """Facts per Wikidata ID, kept across runs: re-linking only fetches IDs not seen before.

    (The HTTP cache alone isn't enough: batches are keyed by their exact list of IDs, so a
    changed topic list would change every batch.)
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS facts (qid TEXT PRIMARY KEY, description TEXT, "
            "aliases TEXT NOT NULL, dates TEXT NOT NULL, places TEXT NOT NULL)"
        )
        self.known = {r[0] for r in self.conn.execute("SELECT qid FROM facts")}

    def put_batch(
        self,
        qids: Sequence[str],
        labels: dict[str, Any],
        dates: dict[str, Any],
        places: dict[str, Any],
    ) -> None:
        descriptions, aliases = parse_labels(labels)
        by_qid: dict[str, dict[str, list[Any]]] = {q: {"dates": [], "places": []} for q in qids}
        for kind, rows in (("dates", parse_dates(dates)), ("places", parse_places(places))):
            for qid, prop, value in rows:
                if qid in by_qid:
                    by_qid[qid][kind].append([prop, value])
        self.conn.executemany(
            "INSERT OR REPLACE INTO facts VALUES (?, ?, ?, ?, ?)",
            [
                (
                    q,
                    descriptions.get(q),
                    json.dumps(sorted(aliases.get(q, set()))),
                    json.dumps(by_qid[q]["dates"]),
                    json.dumps(by_qid[q]["places"]),
                )
                for q in qids
            ],
        )
        self.conn.commit()
        self.known.update(qids)

    def rows(self) -> Iterator[tuple[str, str | None, list[str], list[Any], list[Any]]]:
        for qid, desc, aliases, dates, places in self.conn.execute("SELECT * FROM facts"):
            yield qid, desc, json.loads(aliases), json.loads(dates), json.loads(places)


def run(settings: PipelineSettings, reporter: Reporter) -> None:
    user_agent = settings.require_wikimedia_contact()
    conn = db.connect(settings.corpus_path)
    db.require_table(conn, "topics", "link")
    db.recreate(conn, SCHEMA)
    client = make_client(settings, user_agent)
    store = FactsStore(settings.http_cache_dir / "wikidata_facts.db")

    topic_of: dict[str, str] = dict(
        conn.execute("SELECT wikidata_qid, id FROM topics WHERE wikidata_qid IS NOT NULL")
    )
    # Earlier runs cached whole batches; replaying the same batches fills the per-ID store.
    all_qids = sorted(topic_of)
    replay = [all_qids[i : i + BATCH] for i in range(0, len(all_qids), BATCH)]
    missing = sorted(q for q in topic_of if q not in store.known)
    fresh = [missing[i : i + BATCH] for i in range(0, len(missing), BATCH)]

    reporter.begin("Fetching Wikidata facts", len(replay) + len(fresh))
    skipped = failed = 0
    for phase, batches in (("replay", replay), ("fresh", fresh)):
        for batch in batches:
            reporter.advance()
            todo = [q for q in batch if q not in store.known]
            if not todo:
                continue
            cache_only = phase == "replay" or (
                settings.link_new_requests is not None
                and client.network_requests >= settings.link_new_requests
            )
            try:
                responses = [
                    client.get_json(
                        WIKIDATA_SPARQL, sparql_params(make(batch)), cache_only=cache_only
                    )
                    for make in (labels_query, dates_query, places_query)
                ]
            except NotCached:
                skipped += phase == "fresh"
                continue
            except (httpx.HTTPError, RuntimeError) as exc:
                # One slow or failing batch shouldn't sink the run; a re-run retries it.
                failed += 1
                reporter.log(f"batch at {batch[0]} failed ({type(exc).__name__}); retried next run")
                continue
            store.put_batch(batch, *responses)

    n_dates = n_places = n_aliases = 0
    for qid, description, aliases, dates, places in store.rows():
        if qid not in topic_of:
            continue
        topic_id = topic_of[qid]
        if description:
            conn.execute("UPDATE topics SET description = ? WHERE id = ?", (description, topic_id))
        n_aliases += _add_aliases(conn, topic_of, {qid: set(aliases)})
        for kind, rows in (("date", dates), ("place", places)):
            conn.executemany(
                "INSERT INTO topic_facts VALUES (?, ?, ?, ?)",
                [(topic_id, kind, prop, json.dumps(value)) for prop, value in rows],
            )
        n_dates += len(dates)
        n_places += len(places)

    topics.rebuild_search_index(conn)
    conn.commit()
    reporter.stat(
        "Dates / places / Wikidata aliases", f"{n_dates:,} / {n_places:,} / {n_aliases:,}"
    )
    left = len([q for q in topic_of if q not in store.known])
    if left or failed:
        reporter.stat("Topics left for a later run", f"{left:,}")
    conn.close()


def _add_aliases(
    conn: sqlite3.Connection, topic_of: dict[str, str], aliases: dict[str, set[str]]
) -> int:
    rows = []
    for qid, names in aliases.items():
        for name in names:
            key = normalize(name)
            if len(key) >= 2:
                rows.append((topic_of[qid], name, key, "wikidata", 1.0))
    conn.executemany("INSERT OR IGNORE INTO topic_aliases VALUES (?, ?, ?, ?, ?)", rows)
    return len(rows)
