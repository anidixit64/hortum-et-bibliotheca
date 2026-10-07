"""Shared building blocks for hortum-et-bibliotheca services."""

from hortum_common.app import create_app
from hortum_common.settings import ServiceSettings

__all__ = ["ServiceSettings", "create_app"]
