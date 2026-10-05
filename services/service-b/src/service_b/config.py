from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from hortum_common import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="SERVICE_B_", env_file=".env", extra="ignore")

    service_name: str = "service-b"
    service_a_url: str = "http://localhost:8001"
    http_timeout_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
