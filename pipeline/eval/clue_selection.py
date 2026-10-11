"""How well each topic's picked clues follow the selection rules, across the whole corpus.

    uv run python pipeline/eval/clue_selection.py [--min-questions 6] [--show Q2791 ...]

For topics asked at least ``--min-questions`` times:
- sentence labels: picks labeled by the clue's opening words instead of a term
- duplicate labels: two picks whose labels are the same words (plurals folded)
- order breaks: a pick ranked above one seen in more questions
- skipped common: a pick from fewer than 3 questions while an eligible 3+ question
  clue went unpicked
- 3+ share: picks seen in 3 or more questions
"""

import argparse
import itertools
import sqlite3
from collections import defaultdict
from pathlib import Path

from hortum_common.text import normalize

COMMON = 3


def label_key(label: str) -> frozenset[str]:
    return frozenset(normalize(label.rstrip("…"), singularize=True).split())


def is_sentence(label: str) -> bool:
    return label.endswith("…") or len(label.split()) > 6


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/build/corpus.db")
    parser.add_argument("--min-questions", type=int, default=6)
    parser.add_argument("--show", nargs="*", default=[])
    args = parser.parse_args()
    conn = sqlite3.connect(Path(args.db))

    rows = conn.execute(
        "SELECT s.topic_id, s.cluster_id, s.rank, s.eligible, s.display_label, s.n_questions, "
        "COALESCE(s.skipped, '') "
        "FROM cluster_scores s "
        "JOIN topics t ON t.id = s.topic_id WHERE t.n_tossups >= ?",
        (args.min_questions,),
    ).fetchall()
    by_topic: dict[str, list[tuple[int, int | None, int, str, int]]] = defaultdict(list)
    skipped: dict[int, str] = {}
    for topic_id, cid, rank, eligible, label, n, why in rows:
        by_topic[topic_id].append((cid, rank, eligible, label, n))
        skipped[cid] = why

    totals = dict.fromkeys(
        ["topics", "picks", "sentence", "duplicate", "order", "skipped", "common"], 0
    )
    bad_topics: dict[str, set[str]] = defaultdict(set)
    for topic_id, clusters in by_topic.items():
        picks = sorted((c for c in clusters if c[1] is not None), key=lambda c: c[1])
        if not picks:
            continue
        totals["topics"] += 1
        totals["picks"] += len(picks)
        totals["common"] += sum(c[4] >= COMMON for c in picks)
        for c in picks:
            if is_sentence(c[3]):
                totals["sentence"] += 1
                bad_topics["sentence"].add(topic_id)
        for a, b in itertools.combinations(picks, 2):
            ka, kb = label_key(a[3]), label_key(b[3])
            if ka and kb and (ka <= kb or kb <= ka):
                totals["duplicate"] += 1
                bad_topics["duplicate"].add(topic_id)
            if b[4] > a[4]:  # b ranked lower but seen in more questions
                totals["order"] += 1
                bad_topics["order"].add(topic_id)
        unpicked_common = [c for c in clusters if c[1] is None and c[2] and c[4] >= COMMON]
        if unpicked_common:
            n = sum(c[4] < COMMON for c in picks)
            totals["skipped"] += min(n, len(unpicked_common))
            if n:
                bad_topics["skipped"].add(topic_id)

    picks = max(totals["picks"], 1)
    print(f"topics {totals['topics']:,}, picks {totals['picks']:,}")
    print(
        f"  sentence labels   {totals['sentence']:6,}  ({totals['sentence'] / picks:.1%} of picks)"
    )
    n_dup = len(bad_topics["duplicate"])
    print(f"  duplicate labels  {totals['duplicate']:6,}  pairs in {n_dup:,} topics")
    print(f"  order breaks      {totals['order']:6,}  pairs in {len(bad_topics['order']):,} topics")
    print(f"  skipped common    {totals['skipped']:6,}  in {len(bad_topics['skipped']):,} topics")
    print(f"  3+ question picks {totals['common']:6,}  ({totals['common'] / picks:.1%} of picks)")

    for topic_id in args.show:
        name = conn.execute("SELECT display_name FROM topics WHERE id = ?", (topic_id,)).fetchone()
        print(f"\n== {name[0] if name else topic_id}")
        for cid, rank, eligible, label, n in sorted(
            by_topic.get(topic_id, []), key=lambda c: (c[1] is None, c[1] or 0, -c[4])
        )[:14]:
            text = conn.execute(
                "SELECT c.text FROM clue_clusters k "
                "JOIN clues c ON c.id = k.representative_clue_id WHERE k.id = ?",
                (cid,),
            ).fetchone()[0]
            print(
                f"  {rank or '-':>2} {n}q {'' if eligible else '(x) '}{label!r:40.40}  {text[:70]}"
            )
    conn.close()


if __name__ == "__main__":
    main()
