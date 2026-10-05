from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from hortum_common import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    service_name: str = "gateway"
    service_a_url: str = "http://localhost:8001"
    service_b_url: str = "http://localhost:8002"
    upstream_timeout_seconds: float = 10.0

    def upstreams(self) -> dict[str, str]:
        """Maps the first path segment under /api to a backend base URL."""
        return {"a": self.service_a_url, "b": self.service_b_url}


@lru_cache
def get_settings() -> Settings:
    return Settings()
