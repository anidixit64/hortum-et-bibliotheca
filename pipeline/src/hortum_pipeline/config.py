from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIPELINE_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    # Committed to git: hand fixes must survive rebuilding corpus.db.
    overrides_dir: Path = Path("pipeline/overrides")
    # Wikimedia refuses requests unless the User-Agent includes contact details (a URL or
    # an email), e.g. "hortum-et-bibliotheca/0.1 (https://github.com/you/repo; you@example.com)".
    wikimedia_user_agent: str = ""

    # Answers below this confidence are listed for review.
    review_threshold: float = 0.8
    # Answers below this confidence (and not fixed by hand) stay out of topics.
    group_min_confidence: float = 0.5

    # Linking: only groups with at least this many questions are searched; at most this
    # many *new* web requests per run (cached ones are free). None means no limit.
    link_min_tossups: int = 1
    link_new_requests: int | None = None
    link_min_score: float = 0.2
    # Clue clustering (chosen against pipeline/eval/labeled_clues.yaml: pairwise F1 0.76).
    cluster_threshold: float = 0.6
    cluster_term_bonus: float = 0.2
    # Clue scoring (see hortum_pipeline/score.py), tuned by a sweep over the labeled clues
    # with the tracer guard that Invisible Man keeps Ras the Exhorter and the Battle Royal:
    # precision@5 0.913, recall@10 0.798.
    score_power_bonus: float = 0.0
    score_specificity_exponent: float = 0.0
    score_min_sets: int = 2
    score_frequency_mode: str = "sqrt"
    score_earliness_exponent: float = 0.25
    link_min_similarity: float = 0.05

    def require_wikimedia_contact(self) -> str:
        agent = self.wikimedia_user_agent.strip()
        if "@" not in agent and "http" not in agent:
            raise RuntimeError(
                "Wikimedia requires contact details in the User-Agent. Set "
                "PIPELINE_WIKIMEDIA_USER_AGENT in .env, e.g. "
                '"hortum-et-bibliotheca/0.1 (https://github.com/you/repo; you@example.com)".'
            )
        return agent

    @property
    def raw_tossups(self) -> Path:
        return self.data_dir / "raw" / "tossups.json"

    @property
    def build_dir(self) -> Path:
        return self.data_dir / "build"

    @property
    def corpus_path(self) -> Path:
        return self.build_dir / "corpus.db"

    @property
    def labels_path(self) -> Path:
        """Hand-labeled clues worth knowing (see pipeline/eval/labeled_clues.yaml)."""
        return self.overrides_dir.parent / "eval" / "labeled_clues.yaml"

    @property
    def tracers_path(self) -> Path:
        """Questions followed through every stage (see pipeline/eval/tracers.yaml)."""
        return self.overrides_dir.parent / "eval" / "tracers.yaml"

    @property
    def answer_overrides_path(self) -> Path:
        return self.overrides_dir / "answers.jsonl"

    @property
    def http_cache_dir(self) -> Path:
        return self.data_dir / "cache" / "http"
