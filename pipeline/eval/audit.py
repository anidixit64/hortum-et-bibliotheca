"""Phase 1 statistical audit: judge a fixed random sample of questions by hand.

    uv run python pipeline/eval/audit.py sample   # print the sample to judge
    uv run python pipeline/eval/audit.py score    # read judgments, print accuracy bounds

Judgments live in phase1_audit.json next to this file: for each sampled question,
whether the parsed answer is right and whether its topic is the right one (a topic
left unlinked counts as right only if no single Wikipedia article fits).
"""

import json
import random
import sqlite3
import sys
from pathlib import Path

from scipy.stats import beta

HERE = Path(__file__).parent
AUDIT = HERE / "phase1_audit.json"
CORPUS = Path("data/build/corpus.db")
SEED, SIZE = 20261007, 100


def sample() -> list[dict[str, str]]:
    conn = sqlite3.connect(f"file:{CORPUS}?mode=ro", uri=True)
    ids = sorted(r[0] for r in conn.execute("SELECT id FROM tossups"))
    chosen = random.Random(SEED).sample(ids, SIZE)
    out = []
    for tid in chosen:
        row = conn.execute(
            """
            SELECT t.answer_text, a.main, a.source, tp.display_name, tp.wikipedia_title,
                   substr(t.question_text, -160)
            FROM tossups t JOIN answer_parses a ON a.tossup_id = t.id
            LEFT JOIN tossup_topics tt ON tt.tossup_id = t.id
            LEFT JOIN topics tp ON tp.id = tt.topic_id
            WHERE t.id = ?
            """,
            (tid,),
        ).fetchone()
        answer, main, source, topic, title, ending = row
        out.append(
            {
                "id": tid,
                "answer_line": answer,
                "parsed": main,
                "source": source,
                "topic": topic or "",
                "wikipedia": title or "",
                "question_end": ending,
            }
        )
    return out


def lower_bound(successes: int, n: int, confidence: float = 0.95) -> float:
    """One-sided Clopper-Pearson lower bound on the true accuracy."""
    return 0.0 if successes == 0 else float(beta.ppf(1 - confidence, successes, n - successes + 1))


def score() -> None:
    data = json.loads(AUDIT.read_text())
    items = data["items"]
    for field in ("parse_ok", "link_ok"):
        k = sum(1 for it in items if it[field])
        print(
            f"{field}: {k}/{len(items)} correct; with 95% confidence the true rate is "
            f"≥ {lower_bound(k, len(items)):.1%}"
        )


if __name__ == "__main__":
    if sys.argv[1:] == ["sample"]:
        for i, it in enumerate(sample()):
            topic = it["wikipedia"] or "(local) " + it["topic"][:40]
            line = it["answer_line"][:90]
            print(f"{i}|{line}|P={it['parsed'][:50]}|T={topic}|…{it['question_end'][-90:]}")
    else:
        score()
