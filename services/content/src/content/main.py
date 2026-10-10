from fastapi import FastAPI

from content import db, routes
from content.config import Settings, get_settings
from hortum_common import create_app


def build_app(settings: Settings) -> FastAPI:
    app = create_app(settings, [routes.router])
    app.state.db = db.connect(settings.db_path)
    return app


app = build_app(get_settings())
