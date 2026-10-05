from fastapi import FastAPI

from catalog.config import Settings, get_settings
from hortum_common import create_app


def build_app(settings: Settings) -> FastAPI:
    async def corpus_present() -> bool:
        # Not ready until the pipeline has built corpus.db.
        return settings.corpus_path.is_file()

    return create_app(settings, readiness_checks=[corpus_present])


app = build_app(get_settings())
