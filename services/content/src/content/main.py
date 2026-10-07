from fastapi import FastAPI

from content.config import Settings, get_settings
from hortum_common import create_app


def build_app(settings: Settings) -> FastAPI:
    return create_app(settings)


app = build_app(get_settings())
