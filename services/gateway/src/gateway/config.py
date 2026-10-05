from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from hortum_common import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    service_name: str = "gateway"
    catalog_url: str = "http://localhost:8001"
    content_url: str = "http://localhost:8002"
    study_url: str = "http://localhost:8003"
    upstream_timeout_seconds: float = 10.0

    def upstreams(self) -> dict[str, str]:
        """Maps the first path segment under /api to a backend base URL."""
        return {"catalog": self.catalog_url, "content": self.content_url, "study": self.study_url}


@lru_cache
def get_settings() -> Settings:
    return Settings()
