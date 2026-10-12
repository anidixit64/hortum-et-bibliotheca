from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from hortum_common import ServiceSettings

# Educational channels whose videos may appear on a topic page, matched by channel name as
# YouTube reports it (case-insensitive). Earlier entries rank higher. Edit freely.
DEFAULT_VIDEO_CHANNELS = [
    # Original Education/Science
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
    "Wondrium",
    # Literature & Writing
    "The School of Life",
    "Wisecrack",
    "Literature Savant",
    "Nerdwriter1",
    "John Green",
    "GCSE English Literature",
    # History (Regional/Specific)
    "Fall of Civilizations",
    "History Hit",
    "The Great War",
    "Epic History TV",
    "Timeline - World History Documentaries",
    "BazBattles",
    "Voices of the Past",
    # Science (Specific Disciplines)
    "ElectroBOOM",
    "Practical Engineering",
    "Steve Mould",
    "Kyle Hill",
    "Anton Petrov",
    "Dr. Becky",
    "Sabine Hossenfelder",
    "Computerphile",
    "Code Bullet",
    "Two Minute Papers",
    "ASAPScience",
    "Deep Sky Videos",
    "Physics Girl",
    "NileRed",
    "Professor Dave Explains",
    # Arts & Architecture
    "The Art Assignment",
    "Art21",
    "Perspective",
    "Design Theory",
    "The B1M",
    "Archimarathon",
    "Royal Academy of Arts",
    "Andrew Price",
    # Fine Arts (Music/Performance)
    "Adam Neely",
    "Rick Beato",
    "Nahre Sol",
    "Sideways",
    "Tan Dun",
    "Inside the Score",
    "Early Music Sources",
    "Tantacrul",
    # Social Sciences
    "Alt Shift X",
    "Tom Scott",
    "ColdFusion",
    "Vox",
    "Second Thought",
    "Economics Explained",
    "Polymatter",
    "CGP Grey",
    "Lemmino",
    "Academy of Ideas",
    "Philosophy Tube",
    "CrashCourse Sociology",
    # Pop Culture & Media Analysis
    "Every Frame a Painting",
    "Lessons from the Screenplay",
    "Folding Ideas",
    "Patrick (H) Willems",
    "Writing on Games",
    "Summoning Salt",
    "Ahoy",
    "Game Maker's Toolkit",
    "Kaptainkristian",
    "CinemaWins",
    "Movies with Mikey",
    "Lindsey Ellis",
    # Math & Engineering
    "Stand-up Maths",
    "Mathologer",
    "Veritasium",
    "Real Engineering",
    "Branch Education",
    "Applied Science",
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

    # Generation (Phase 6). Chains are tried in order; see content/generate.
    use_claude_code: bool = True  # false: Gemini only, and the worker can run in Docker
    claude_code_path: str = ""  # default: `claude` on the PATH or the VS Code extension's copy
    gemini_api_key: str = ""  # free key from Google AI Studio
    # Claude Code first (the subscription), then free Gemini models. The free tier caps each
    # model separately (gemini-3.8-flash: 20 requests a day), so the chains walk through
    # several: when one is out for the day the next takes over. Pro models aren't free;
    # Gemma writes its reasoning before the JSON (see generate.gemini.reply_json).
    light_chain: str = (
        "claude_code:haiku,gemini:gemini-3.5-flash-lite,gemini:gemini-3.1-flash-lite,"
        "gemini:gemma-4-31b-it,gemini:gemma-4-26b-a4b-it"
    )
    writing_chain: str = (
        "claude_code:opus,gemini:gemini-3.8-flash,gemini:gemini-3.5-flash,"
        "gemini:gemini-3.7-flash,gemini:gemma-4-31b-it"
    )
    generation_timeout_seconds: float = 300.0
    # NER at first open: a Python with spaCy and en_core_web_trf (make ner-env); empty = off.
    ner_python: str = ""

    worker_poll_seconds: float = 2.0
    job_max_attempts: int = 5
    request_timeout_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
