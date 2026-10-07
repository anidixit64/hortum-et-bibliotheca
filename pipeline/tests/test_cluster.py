import json
import sqlite3
from collections.abc import Sequence

import numpy as np
import pytest

from hortum_pipeline import answer_stage, clues, cluster, grouping, ingest
from hortum_pipeline.config import PipelineSettings
from hortum_pipeline.progress import NullReporter


def fake_embedder() -> cluster.Embedder:
    """Deterministic stand-in for MiniLM: clues sharing their first word point the same way."""

    def embed(texts: Sequence[str]) -> np.ndarray:
        out = []
        for text in texts:
            rng = np.random.default_rng(abs(hash(text.split()[0])) % 2**32)
            v = rng.normal(size=cluster.DIM)
            out.append(v / np.linalg.norm(v))
        return np.array(out, dtype=np.float32)

    return embed


def test_similarity_adds_bonus_per_shared_term() -> None:
    vectors = np.eye(3, dtype=np.float32)
    sim = cluster.similarity(vectors, [["Brockway", "Liberty Paints"], ["brockway"], []], 0.2)
    assert sim[0, 1] == pytest.approx(0.2)
    assert sim[0, 2] == 0.0
    assert sim[0, 0] == 1.0


def test_cluster_topic_merges_close_vectors() -> None:
    sim = np.array([[1.0, 0.9, 0.1], [0.9, 1.0, 0.1], [0.1, 0.1, 1.0]])
    labels = cluster.cluster_topic(sim, threshold=0.6)
    assert labels[0] == labels[1] != labels[2]


def test_summarize_picks_medoid_and_common_terms() -> None:
    sim = np.array([[1.0, 0.8, 0.7], [0.8, 1.0, 0.9], [0.7, 0.9, 1.0]])
    medoid, label, terms = cluster.summarize(
        ["a", "b", "c"], [["Ras"], ["Ras", "Harlem"], ["Harlem", "Ras"]], sim
    )
    assert medoid == 1
    assert label == "Ras" and terms[:2] == ["Ras", "Harlem"]


def test_stage_clusters_and_caches(settings: PipelineSettings) -> None:
    for stage in (ingest, answer_stage, grouping):
        stage.run(settings, NullReporter())
    # Topics come from linking; for this offline test, make each group its own topic.
    conn = sqlite3.connect(settings.corpus_path)
    conn.executescript(
        "CREATE TABLE tossup_topics (tossup_id TEXT PRIMARY KEY, topic_id TEXT);"
        "INSERT INTO tossup_topics SELECT tossup_id, 'g' || group_id FROM tossup_groups;"
    )
    conn.commit()
    clues.run(settings, NullReporter())
    cluster.run(settings, NullReporter(), fake_embedder)

    topical = conn.execute(
        "SELECT COUNT(*) FROM clues WHERE kind = 'clue' AND topic_id IS NOT NULL"
    ).fetchone()[0]
    assigned = conn.execute("SELECT COUNT(*) FROM clue_cluster_members").fetchone()[0]
    assert assigned == topical > 0
    label, terms = conn.execute("SELECT label, key_terms FROM clue_clusters LIMIT 1").fetchone()
    assert label and isinstance(json.loads(terms), list)

    def no_embedding() -> cluster.Embedder:
        raise AssertionError("everything should be cached on the second run")

    cluster.run(settings, NullReporter(), no_embedding)
