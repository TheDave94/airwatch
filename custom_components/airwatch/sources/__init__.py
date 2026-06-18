"""AirWatch data sources.

The source layer is intentionally independent of Home Assistant. Each source
parses a provider's response into the shared :class:`SourceResult` shape defined
in :mod:`.base`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import (
    POLLUTANTS,
    PollutantSeries,
    SourceError,
    SourceResponseError,
    SourceResult,
    SourceStatus,
    SourceUnavailable,
)

if TYPE_CHECKING:
    from .land_steiermark import LandSteiermarkSource
    from .open_meteo import OpenMeteoSource
    from .sensor_community import SensorCommunitySource

__all__ = [
    "POLLUTANTS",
    "LandSteiermarkSource",
    "OpenMeteoSource",
    "PollutantSeries",
    "SensorCommunitySource",
    "SourceError",
    "SourceResponseError",
    "SourceResult",
    "SourceStatus",
    "SourceUnavailable",
]

# Lazy source-client map: attribute name -> (module, class). Keeps
# ``from ...sources import OpenMeteoSource`` working while avoiding the eager
# import that would otherwise double-import a module under ``python -m``.
_LAZY_SOURCES = {
    "OpenMeteoSource": ("open_meteo", "OpenMeteoSource"),
    "SensorCommunitySource": ("sensor_community", "SensorCommunitySource"),
    "LandSteiermarkSource": ("land_steiermark", "LandSteiermarkSource"),
}


def __getattr__(name: str) -> object:
    """Lazily expose source clients without importing them at package load."""
    target = _LAZY_SOURCES.get(name)
    if target is not None:
        import importlib

        module = importlib.import_module(f".{target[0]}", __name__)
        return getattr(module, target[1])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
