from functools import lru_cache
from pathlib import Path

from pydantic_settings import SettingsConfigDict

from hortum_common import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="CATALOG_", env_file=".env", extra="ignore")

    service_name: str = "catalog"
    corpus_path: Path = Path("data/build/corpus.db")


@lru_cache
def get_settings() -> Settings:
    return Settings()
