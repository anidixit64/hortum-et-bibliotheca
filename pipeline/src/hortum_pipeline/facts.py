"""Stage 4b: dates, places, descriptions and aliases from Wikidata (via SPARQL).

SPARQL returns only the properties we need, which keeps responses small; fetching full
entities would download megabytes of claims for items like countries.
"""

import json
import re
import sqlite3
from collections.abc import Iterator, Sequence
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


def run(settings: PipelineSettings, reporter: Reporter) -> None:
    user_agent = settings.require_wikimedia_contact()
    conn = db.connect(settings.corpus_path)
    db.require_table(conn, "topics", "link")
    db.recreate(conn, SCHEMA)
    client = make_client(settings, user_agent)

    topic_of: dict[str, str] = dict(
        conn.execute("SELECT wikidata_qid, id FROM topics WHERE wikidata_qid IS NOT NULL")
    )
    qids = sorted(topic_of)
    batches = [qids[i : i + BATCH] for i in range(0, len(qids), BATCH)]
    reporter.begin("Fetching Wikidata facts", len(batches))
    n_dates = n_places = n_aliases = 0
    skipped = failed = 0
    for batch in batches:
        cache_only = (
            settings.link_new_requests is not None
            and client.network_requests >= settings.link_new_requests
        )
        try:
            labels = client.get_json(
                WIKIDATA_SPARQL, sparql_params(labels_query(batch)), cache_only=cache_only
            )
            dates = client.get_json(
                WIKIDATA_SPARQL, sparql_params(dates_query(batch)), cache_only=cache_only
            )
            places = client.get_json(
                WIKIDATA_SPARQL, sparql_params(places_query(batch)), cache_only=cache_only
            )
        except NotCached:
            skipped += 1
            reporter.advance()
            continue
        except (httpx.HTTPError, RuntimeError) as exc:
            # One slow or failing batch shouldn't sink the run; a re-run retries it.
            failed += 1
            reporter.log(
                f"batch starting {batch[0]} failed ({type(exc).__name__}); will retry next run"
            )
            reporter.advance()
            continue

        descriptions, aliases = parse_labels(labels)
        conn.executemany(
            "UPDATE topics SET description = ? WHERE wikidata_qid = ?",
            [(d, q) for q, d in descriptions.items()],
        )
        n_aliases += _add_aliases(conn, topic_of, aliases)
        for kind, rows in (("date", parse_dates(dates)), ("place", parse_places(places))):
            conn.executemany(
                "INSERT INTO topic_facts VALUES (?, ?, ?, ?)",
                [(topic_of[q], kind, prop, json.dumps(value)) for q, prop, value in rows],
            )
            if kind == "date":
                n_dates += len(rows)
            else:
                n_places += len(rows)
        conn.commit()
        reporter.advance()

    topics.rebuild_search_index(conn)
    conn.commit()
    reporter.stat(
        "Dates / places / Wikidata aliases", f"{n_dates:,} / {n_places:,} / {n_aliases:,}"
    )
    if skipped or failed:
        reporter.stat("Batches left for a later run", f"{skipped + failed:,}")
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
