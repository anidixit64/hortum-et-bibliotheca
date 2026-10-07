from fastapi import FastAPI

from hortum_common import create_app
from study.config import Settings, get_settings


def build_app(settings: Settings) -> FastAPI:
    return create_app(settings)


app = build_app(get_settings())
