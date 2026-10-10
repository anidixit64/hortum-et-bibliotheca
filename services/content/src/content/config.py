from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from hortum_common import ServiceSettings

# Educational channels whose videos may appear on a topic page, matched by channel name as
# YouTube reports it (case-insensitive). Earlier entries rank higher. Edit freely.
DEFAULT_VIDEO_CHANNELS = [
    "CrashCourse",
    "Khan Academy",
    "TED-Ed",
    "PBS Eons",
    "PBS Space Time",
    "Kurzgesagt – In a Nutshell",
    "SciShow",
    "Smithsonian Channel",
    "Overly Sarcastic Productions",
    "Kings and Generals",
    "Extra History",
    "The Royal Institution",
    "Periodic Videos",
    "Numberphile",
    "3Blue1Brown",
    "Veritasium",
    "Great Art Explained",
    "The Great Courses Plus",
]


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="CONTENT_", env_file=".env", extra="ignore")

    service_name: str = "content"
    db_path: Path = Path("data/content.db")
    catalog_url: str = "http://localhost:8001"

    # Wikimedia refuses requests whose User-Agent has no contact (a URL or email).
    wikimedia_user_agent: str = ""
    # Open Library and others: identifies the project without personal details.
    user_agent: str = (
        "hortum-et-bibliotheca/0.1 (+https://github.com/anidixit64/hortum-et-bibliotheca)"
    )
    youtube_api_key: str = ""  # without one, videos stay "unavailable"
    video_channels: list[str] = Field(default_factory=lambda: list(DEFAULT_VIDEO_CHANNELS))

    worker_poll_seconds: float = 2.0
    job_max_attempts: int = 5
    request_timeout_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
