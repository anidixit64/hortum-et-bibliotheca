from collections.abc import Callable
from dataclasses import dataclass

from hortum_pipeline.config import PipelineSettings

StageFn = Callable[[PipelineSettings], None]


@dataclass(frozen=True)
class Stage:
    name: str
    summary: str
    phase: int  # build-plan phase that implements it (docs/ARCHITECTURE.md §10)
    run: StageFn | None = None


# Order matters: each stage reads what the previous ones wrote.
STAGES: tuple[Stage, ...] = (
    Stage("ingest", "Load the NDJSON dump, unwrap extended JSON, dedupe", phase=1),
    Stage("parse-answers", "Parse answer lines into required/accept/prompt/reject", phase=1),
    Stage("group", "Group answers into candidate topics", phase=1),
    Stage("link", "Link topics to Wikipedia/Wikidata and merge by QID", phase=1),
    Stage("facts", "Fetch Wikidata dates, places and descriptions", phase=1),
    Stage("clues", "Split questions into clues with positions and key terms", phase=2),
    Stage("cluster", "Cluster clues that state the same fact", phase=2),
    Stage("score", "Score clue clusters for impact and heatmap statistics", phase=2),
    Stage("relate", "Find related topics mentioned in clues", phase=2),
    Stage("confuse", "Find commonly confused topics", phase=2),
    Stage("snapshot", "Write one denormalized snapshot row per topic", phase=2),
)

STAGES_BY_NAME = {stage.name: stage for stage in STAGES}
