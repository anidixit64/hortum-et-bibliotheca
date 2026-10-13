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


def _env_file() -> Path:
    """The repo's ``.env``, wherever the worker was started from."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "services").is_dir():
            return parent / ".env"
    return Path(".env")


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="CONTENT_", env_file=_env_file(), extra="ignore")

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
    use_claude_code: bool = False  # false: Gemini only, and the worker can run in Docker
    claude_code_path: str = ""  # default: `claude` on the PATH or the VS Code extension's copy
    gemini_api_key: str = ""  # free key from Google AI Studio
    groq_api_key: str = ""  # free key from console.groq.com (8K TPM — small prompts only)
    cerebras_api_key: str = ""  # cloud.cerebras.ai ($5 free credit, very generous limits)
    sambanova_api_key: str = ""  # cloud.sambanova.ai ($5 free credit, 90 days)
    openrouter_api_key: str = ""  # free key from openrouter.ai/keys
    nvidia_api_key: str = ""  # free key from build.nvidia.com
    github_api_key: str = ""  # free token from github.com/settings/tokens
    mistral_api_key: str = ""  # free key from console.mistral.ai
    admin_pin: str = ""  # PIN for the /settings page; empty = admin disabled
    # Claude Code first (the subscription), then free providers. Each provider's free tier
    # has its own daily/minute caps, so the chains walk through several: when one is out
    # the next takes over.
    #
    # Groq free tier: 8K TPM, 200K TPD — too tight for writing (our prompts send the full
    # Wikipedia article, 20-80K tokens). Good only for the light chain (theme, cleanup).
    # Models: gpt-oss-20b (1000 t/s), gpt-oss-120b (500 t/s), qwen3.8-27b.
    #
    # Cerebras: $5 free credit, needs a payment method. qwen-3.8-27b is very generous
    # (450 RPM, 150K tokens/min) — handles everything including long writing prompts.
    #
    # Gemini free tier: 20 RPD per model, but many models. Handles long prompts fine.
    light_chain: str = (
        "claude_code:haiku,"
        "cerebras:qwen-3.8-27b,groq:openai/gpt-oss-20b,"
        "mistral:mistral-large-latest,"
        "gemini:gemini-3.5-flash-lite,gemini:gemini-3.1-flash-lite,"
        "gemini:gemma-4-31b-it,gemini:gemma-4-26b-a4b-it"
    )
    writing_chain: str = (
        "claude_code:opus,"
        "cerebras:qwen-3.8-27b,cerebras:gpt-oss-120b,"
        "groq:openai/gpt-oss-20b,"
        "mistral:mistral-large-latest,"
        "gemini:gemini-3.8-flash,gemini:gemini-3.5-flash,"
        "gemini:gemini-3.7-flash,gemini:gemma-4-31b-it"
    )
    # One model call. A provider that hangs is abandoned after five minutes and the chain
    # tries the next configured model.
    generation_timeout_seconds: float = 300.0
    # NER at first open: a Python with spaCy and en_core_web_trf (make ner-env); empty = off.
    ner_python: str = ""

    worker_threads: int = 8
    worker_poll_seconds: float = 2.0
    job_max_attempts: int = 5
    request_timeout_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
