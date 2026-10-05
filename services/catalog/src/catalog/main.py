from fastapi import FastAPI

from catalog import routes
from catalog.config import Settings, get_settings
from catalog.search import SearchIndex
from hortum_common import create_app


def build_app(settings: Settings) -> FastAPI:
    async def corpus_present() -> bool:
        # Not ready until the pipeline has built corpus.db.
        return settings.corpus_path.is_file()

    app = create_app(settings, [routes.router], readiness_checks=[corpus_present])
    app.state.search_index = SearchIndex(settings.corpus_path)
    return app


app = build_app(get_settings())
