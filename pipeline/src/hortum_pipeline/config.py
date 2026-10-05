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
    def answer_overrides_path(self) -> Path:
        return self.overrides_dir / "answers.jsonl"

    @property
    def http_cache_dir(self) -> Path:
        return self.data_dir / "cache" / "http"
