"""Phase 2 acceptance audit: judge a fixed random sample of topic pages by hand.

    uv run python pipeline/eval/audit_phase2.py sample   # print the pages to judge
    uv run python pipeline/eval/audit_phase2.py score    # read judgments, print bounds

The sample is 30 topics asked at least 10 times (thinner pages hold too little to judge),
read from the topic records the catalog serves. Judgments live in phase2_audit.json:

* clues: for each of the top 5, is it a real, specific fact about the topic, labeled
  correctly, with card text that matches the label?
* related: for each of the top 5, is it truly related, and the right topic for the name?
* confusions: for each, is it a pair players plausibly mix up?
* page_ok: taken whole, could someone study from this page without being misled?
"""

import json
import random
import sqlite3
import sys
from pathlib import Path

from scipy.stats import beta

HERE = Path(__file__).parent
AUDIT = HERE / "phase2_audit.json"
CORPUS = Path("data/build/corpus.db")
SEED, SIZE, MIN_QUESTIONS, TOP = 20261008, 30, 10, 5


def sample() -> list[dict[str, object]]:
    conn = sqlite3.connect(f"file:{CORPUS}?mode=ro", uri=True)
    ids = sorted(
        r[0] for r in conn.execute("SELECT id FROM topics WHERE n_tossups >= ?", (MIN_QUESTIONS,))
    )
    out = []
    for topic_id in random.Random(SEED).sample(ids, SIZE):
        record = json.loads(
            conn.execute(
                "SELECT json FROM topic_snapshots WHERE topic_id = ?", (topic_id,)
            ).fetchone()[0]
        )
        topic = record["topic"]
        out.append(
            {
                "id": topic_id,
                "name": topic["name"],
                "description": topic["description"],
                "n_tossups": topic["stats"]["n_tossups"],
                "clues": [
                    {"label": c["label"], "n_sets": c["n_sets"], "text": c["text"]}
                    for c in record["clues"][:TOP]
                ],
                "related": [
                    {"name": r["name"], "why": r["example"]["text"]}
                    for r in record["related"][:TOP]
                ],
                "confusions": [
                    {"name": c["name"], "reasons": c["reasons"]} for c in record["confusions"]
                ],
            }
        )
    return out


def lower_bound(successes: int, n: int, confidence: float = 0.95) -> float:
    """One-sided Clopper-Pearson lower bound on the true rate."""
    return 0.0 if successes == 0 else float(beta.ppf(1 - confidence, successes, n - successes + 1))


def score() -> None:
    data = json.loads(AUDIT.read_text(encoding="utf-8"))
    measures = {
        "clue correct (top 5)": [ok for t in data["items"] for ok in t["clue_ok"]],
        "related topic correct (top 5)": [ok for t in data["items"] for ok in t["related_ok"]],
        "confusion sensible": [ok for t in data["items"] for ok in t["confusion_ok"]],
        "page usable as a whole": [t["page_ok"] for t in data["items"]],
    }
    for name, oks in measures.items():
        k, n = sum(oks), len(oks)
        if n:
            print(
                f"{name:32} {k:4d} / {n:<4d} {k / n:6.1%}   95% lower bound {lower_bound(k, n):.1%}"
            )
    for t in data["items"]:
        if t.get("notes"):
            print(f"- {t['name']}: {t['notes']}")


if __name__ == "__main__":
    if sys.argv[1:] == ["sample"]:
        for page in sample():
            print(json.dumps(page, ensure_ascii=False))
    elif sys.argv[1:] == ["score"]:
        score()
    else:
        sys.exit(__doc__)
