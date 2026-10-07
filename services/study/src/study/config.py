from functools import lru_cache
from pathlib import Path

from pydantic_settings import SettingsConfigDict

from hortum_common import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="STUDY_", env_file=".env", extra="ignore")

    service_name: str = "study"
    db_path: Path = Path("data/study.db")
    # Nightly copies of study.db go here; it is the only data that can't be rebuilt.
    backup_dir: Path | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
