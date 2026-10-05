from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIPELINE_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    wikimedia_user_agent: str = "hortum-et-bibliotheca/0.1 (personal study tool)"

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
    def http_cache_dir(self) -> Path:
        return self.data_dir / "cache" / "http"
