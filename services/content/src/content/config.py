from functools import lru_cache
from pathlib import Path

from pydantic_settings import SettingsConfigDict

from hortum_common import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="CONTENT_", env_file=".env", extra="ignore")

    service_name: str = "content"
    db_path: Path = Path("data/content.db")
    catalog_url: str = "http://localhost:8001"


@lru_cache
def get_settings() -> Settings:
    return Settings()
