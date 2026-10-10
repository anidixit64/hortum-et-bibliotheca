from functools import lru_cache
from pathlib import Path

from pydantic_settings import SettingsConfigDict

from hortum_common import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="STUDY_", env_file=".env", extra="ignore")

    service_name: str = "study"
    db_path: Path = Path("data/study.db")
    catalog_url: str = "http://localhost:8001"
    catalog_timeout_seconds: float = 10.0
    # Nightly copies of study.db go here; it is the only data that can't be rebuilt.
    backup_dir: Path | None = None
    backup_hour_utc: int = 9
    backups_kept: int = 14


@lru_cache
def get_settings() -> Settings:
    return Settings()
