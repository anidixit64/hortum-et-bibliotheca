"""How well do the ranked clues match the hand-labeled clues worth knowing?"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from hortum_pipeline.labels import LabeledTopic, load

# A pick matches a labeled clue through its label, key terms, representative clue and a
# few members: reading dozens of members would credit big merged clusters with every
# fact any member happens to mention.
_MEMBER_SAMPLE = 5


@dataclass
class TopicResult:
    topic: LabeledTopic
    picks: list[str] = field(default_factory=list)  # ranked cluster labels
    pick_hits: list[bool] = field(default_factory=list)  # does pick i match any label?
    found: set[int] = field(default_factory=set)  # labeled clues found in the top 10

    @property
    def precision_at_5(self) -> float:
        top = self.pick_hits[:5]
        return sum(top) / len(top) if top else 0.0

    @property
    def recall_at_10(self) -> float:
        return len(self.found) / len(self.topic.clues)


def cluster_text(conn: sqlite3.Connection, cluster_id: int) -> str:
    label, terms, representative = conn.execute(
        "SELECT k.label, k.key_terms, c.text FROM clue_clusters k "
        "JOIN clues c ON c.id = k.representative_clue_id WHERE k.id = ?",
        (cluster_id,),
    ).fetchone()
    members = conn.execute(
        "SELECT c.text FROM clue_cluster_members m JOIN clues c ON c.id = m.clue_id "
        "WHERE m.cluster_id = ? LIMIT ?",
        (cluster_id, _MEMBER_SAMPLE),
    ).fetchall()
    return " | ".join([label, terms, representative, *(m[0] for m in members)])


def evaluate(conn: sqlite3.Connection, labels_path: Path) -> list[TopicResult]:
    results = []
    for topic in load(labels_path):
        result = TopicResult(topic)
        for cluster_id, label in conn.execute(
            "SELECT cluster_id, display_label FROM cluster_scores "
            "WHERE topic_id = ? AND rank IS NOT NULL ORDER BY rank",
            (topic.id,),
        ):
            text = cluster_text(conn, cluster_id)
            hits = {i for i, clue in enumerate(topic.clues) if clue.found_in(text)}
            result.picks.append(label)
            result.pick_hits.append(bool(hits))
            result.found |= hits
        results.append(result)
    return results


def summary(results: list[TopicResult]) -> tuple[float, float]:
    n = max(len(results), 1)
    return (
        sum(r.precision_at_5 for r in results) / n,
        sum(r.recall_at_10 for r in results) / n,
    )


def report(results: list[TopicResult]) -> str:
    lines = []
    for r in results:
        marks = "".join("✓" if h else "·" for h in r.pick_hits)
        lines.append(
            f"{r.topic.name[:34]:34} P@5 {r.precision_at_5:.2f}  R@10 {r.recall_at_10:.2f}  "
            f"{marks:10}  {', '.join(r.picks[:5])}"
        )
    p5, r10 = summary(results)
    lines.append(
        f"\nmean precision@5 {p5:.3f} · mean recall@10 {r10:.3f} over {len(results)} topics"
    )
    return "\n".join(lines)
