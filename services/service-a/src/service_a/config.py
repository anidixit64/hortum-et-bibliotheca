from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from hortum_common import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="SERVICE_A_", env_file=".env", extra="ignore")

    service_name: str = "service-a"


@lru_cache
def get_settings() -> Settings:
    return Settings()
