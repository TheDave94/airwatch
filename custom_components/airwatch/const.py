"""Constants for the AirWatch integration.

Intentionally free of ``homeassistant`` imports so importing the package does
not pull in Home Assistant — this keeps the source layer under ``sources/``
testable in isolation (the package ``__init__`` imports only this module).

Adapted from PollenWatch ``const.py``: allergen/species keys → pollutant keys,
the EU pollen sources → the air-quality sources (Open-Meteo/CAMS primary,
Sensor.Community + Land Steiermark secondaries). AirWatch starts at config-entry
version 1, so there is no legacy selection-key alias to carry.
"""

from __future__ import annotations

from typing import Final

from .sources.base import POLLUTANTS

DOMAIN: Final = "airwatch"

# Platforms set up per config entry. Kept as plain strings to avoid importing
# homeassistant.const here; __init__ maps them onto the Platform enum.
PLATFORMS: Final[list[str]] = ["sensor", "binary_sensor"]

# Device holding the cross-source analytics entities (consensus, divergence).
ANALYTICS_DEVICE_NAME: Final = "AirWatch Analytics"

# Attribution text required by the data providers. See README.
ATTRIBUTION_CAMS: Final = (
    "Generated using Copernicus Atmosphere Monitoring Service information. "
    "Air-quality data via Open-Meteo.com."
)
ATTRIBUTION_SENSOR_COMMUNITY: Final = (
    "Contains data from the Sensor.Community citizen network (ODbL)."
)
ATTRIBUTION_LAND_STEIERMARK: Final = "Source: Land Steiermark (Luftgüte)"

# --- source identities ----------------------------------------------------
# The device NAME slugs to the entity-ID prefix
# (sensor.airwatch_<source>_<pollutant>); these strings are load-bearing for
# existing entities and must stay stable once shipped.

# Primary source: Open-Meteo / CAMS — free, keyless, hourly, EU-wide µg/m³.
SOURCE_OPEN_METEO: Final = "open_meteo"
SOURCE_OPEN_METEO_NAME: Final = "Open-Meteo (CAMS)"

# Secondary: Sensor.Community hyperlocal citizen sensors (SDS011 etc.), keyless.
SOURCE_SENSOR_COMMUNITY: Final = "sensor_community"
SOURCE_SENSOR_COMMUNITY_NAME: Final = "Sensor.Community"

# Secondary: Land Steiermark official daily-mean stations. Shipped
# DISABLED-BY-DEFAULT in v1 (no clean live feed yet — see OPEN_QUESTIONS.md Q6).
SOURCE_LAND_STEIERMARK: Final = "land_steiermark"
SOURCE_LAND_STEIERMARK_NAME: Final = "Land Steiermark"

SOURCE_DEVICE_NAMES: Final[dict[str, str]] = {
    SOURCE_OPEN_METEO: "AirWatch Open-Meteo",
    SOURCE_SENSOR_COMMUNITY: "AirWatch Sensor.Community",
    SOURCE_LAND_STEIERMARK: "AirWatch Land Steiermark",
}
SOURCE_DEVICE_MODELS: Final[dict[str, str]] = {
    SOURCE_OPEN_METEO: "CAMS via Open-Meteo",
    SOURCE_SENSOR_COMMUNITY: "Sensor.Community (citizen network)",
    SOURCE_LAND_STEIERMARK: "Austrian network (SensorThings, drift anchor)",
}
SOURCE_CONFIG_URLS: Final[dict[str, str]] = {
    SOURCE_OPEN_METEO: "https://open-meteo.com/",
    SOURCE_SENSOR_COMMUNITY: "https://sensor.community/",
    SOURCE_LAND_STEIERMARK: "https://www.umwelt.steiermark.at/",
}
SOURCE_ATTRIBUTIONS: Final[dict[str, str]] = {
    SOURCE_OPEN_METEO: ATTRIBUTION_CAMS,
    SOURCE_SENSOR_COMMUNITY: ATTRIBUTION_SENSOR_COMMUNITY,
    SOURCE_LAND_STEIERMARK: ATTRIBUTION_LAND_STEIERMARK,
}

# --- config-entry / options keys ------------------------------------------
# Location uses homeassistant.const CONF_LATITUDE / CONF_LONGITUDE; the rest
# are AirWatch-specific. AirWatch starts at v1 — the pollutant selection key is
# canonical from the start (no legacy alias).
CONF_SELECTED_POLLUTANTS: Final = "selected_pollutants"
CONF_UPDATE_INTERVAL: Final = "update_interval"  # minutes

# Multi-source enablement. Stored in options under CONF_SOURCES as
# {source_key: {enabled: bool, ...}}.
CONF_SOURCES: Final = "sources"
CONF_ENABLED: Final = "enabled"
CONF_STATION: Final = "station"  # Land Steiermark single-station ref
# Explicit Sensor.Community station IDs (list[int]); empty → auto-discover by
# distance. Plural — distinct from CONF_STATION (Land Steiermark, singular).
CONF_STATIONS: Final = "stations"
# Max distance (km) to accept a nearest-station match. Shared by Sensor.Community
# (citizen sensors, dense) and Land Steiermark (official stations, sparse — hence
# its own wider default below).
CONF_MAX_DISTANCE_KM: Final = "max_distance_km"
DEFAULT_MAX_DISTANCE_KM: Final = 10.0
# Land Steiermark official stations are sparse; default to a wider search radius.
LAND_STEIERMARK_MAX_DISTANCE_KM: Final = 25.0

# --- per-source update intervals ------------------------------------------
# Open-Meteo / CAMS publishes hourly; a free keyless API — never poll faster.
DEFAULT_UPDATE_INTERVAL_MIN: Final = 60
MIN_UPDATE_INTERVAL_MIN: Final = 60
MAX_UPDATE_INTERVAL_MIN: Final = 24 * 60
# Sensor.Community exposes ~5-minute readings; poll every 15 min (fresh enough,
# easy on the free community feed).
SENSOR_COMMUNITY_UPDATE_INTERVAL_MIN: Final = 15
# Land Steiermark is a slow drift anchor (lagged official feed) — poll slowly.
LAND_STEIERMARK_UPDATE_INTERVAL_MIN: Final = 12 * 60


def new_sources_config() -> dict[str, dict[str, object]]:
    """Default per-source enablement for a new entry.

    Open-Meteo is always on (keyless, primary). Sensor.Community is off by
    default (opt-in, needs a nearby sensor). Land Steiermark is off by default
    until a clean live feed exists (OPEN_QUESTIONS.md Q6).
    """
    return {
        SOURCE_OPEN_METEO: {CONF_ENABLED: True},
        SOURCE_SENSOR_COMMUNITY: {
            CONF_ENABLED: False,
            CONF_MAX_DISTANCE_KM: DEFAULT_MAX_DISTANCE_KM,
            CONF_STATIONS: [],
        },
        SOURCE_LAND_STEIERMARK: {
            CONF_ENABLED: False,
            CONF_STATION: "",
            CONF_MAX_DISTANCE_KM: LAND_STEIERMARK_MAX_DISTANCE_KM,
        },
    }


# --- defaults and guardrails ----------------------------------------------
# v1 onboarding default: all CAMS pollutants enabled (OPEN_QUESTIONS.md Q7).
DEFAULT_SELECTED_POLLUTANTS: Final[list[str]] = list(POLLUTANTS)

# Open-Meteo fetch window. recent_percentile baselines today against the
# trailing ~92 days, so we request the full backfill. forecast_days=5 gives a
# best-effort 5th day.
OPEN_METEO_PAST_DAYS: Final = 92
OPEN_METEO_FORECAST_DAYS: Final = 5
FORECAST_DAYS: Final = 4

# Human-readable pollutant names (UI translations override these; used as a
# fallback and for entity naming). Derived from the canonical pollutant
# registry so a new pollutant is automatically covered.
from .sources.pollutant_registry import CANONICAL_POLLUTANTS as _CANONICAL  # noqa: E402

POLLUTANT_NAMES: Final[dict[str, str]] = {
    k: v.name for k, v in _CANONICAL.items()
}

# --- extra-state-attribute keys exposed by sensors ------------------------
ATTR_FORECAST: Final = "forecast"
ATTR_REQUESTED_LAT: Final = "requested_latitude"
ATTR_REQUESTED_LON: Final = "requested_longitude"
ATTR_SNAPPED_LAT: Final = "snapped_latitude"
ATTR_SNAPPED_LON: Final = "snapped_longitude"
ATTR_GRID_SHIFT_KM: Final = "grid_shift_km"
ATTR_LAST_UPDATED: Final = "source_last_updated"
ATTR_STATION: Final = "station"
# Provenance/threshold attributes (Q4 — expose, don't assert).
ATTR_LEVEL: Final = "level"
ATTR_LEVEL_LABEL: Final = "level_label"
# Provenance-tagged band assessments, keyed by authority (eaqi_classic /
# eaqi_eea_2024 / who_2021 / who_retained / eu_2024_2881 / eu_2008_50_ec). WHO/EU
# authorities carry a LIST of per-averaging-window entries; index authorities a
# single band dict. Authorities are kept DISTINCT — never collapsed into one
# verdict. See pollutant_registry.band_provenance.
ATTR_BANDS: Final = "bands"
# CO convenience conversion (Q3 — exposed as a tagged attribute, not the state).
ATTR_CO_PPM: Final = "value_ppm"
ATTR_CO_PPM_NOTE: Final = "ppm_conversion_note"
# Cross-source consensus source-count badge.
ATTR_SOURCE_COUNT: Final = "source_count"
ATTR_MAX_SOURCES: Final = "max_possible_sources"
