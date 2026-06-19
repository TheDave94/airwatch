"""Data update coordinators for AirWatch.

Per-source ``DataUpdateCoordinator`` pattern: one coordinator per data source,
collected in a small runtime-data container on the config entry. A meta
("analytics") coordinator fans these into cross-source consensus / divergence /
recent-percentile.

Ported ~as-is from PollenWatch ``coordinator.py`` (domain-agnostic). Adapted:
the source set is Open-Meteo (primary, always) + Sensor.Community + Land
Steiermark (secondaries, opt-in); allergens → pollutants throughout.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .analytics import (
    PERCENTILE_WINDOW_DAYS,
    ConsensusResult,
    PercentileResult,
    compute_recent_percentile,
    consensus,
    daily_peaks,
    level_for_source,
    recent_percentile_from_series,
)
from .const import (
    ANALYTICS_DEVICE_NAME,
    CONF_ENABLED,
    CONF_MAX_DISTANCE_KM,
    CONF_SELECTED_POLLUTANTS,
    CONF_SOURCES,
    CONF_STATION,
    CONF_STATIONS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_MAX_DISTANCE_KM,
    DEFAULT_SELECTED_POLLUTANTS,
    DEFAULT_UPDATE_INTERVAL_MIN,
    DOMAIN,
    LAND_STEIERMARK_MAX_DISTANCE_KM,
    LAND_STEIERMARK_UPDATE_INTERVAL_MIN,
    OPEN_METEO_FORECAST_DAYS,
    OPEN_METEO_PAST_DAYS,
    SENSOR_COMMUNITY_UPDATE_INTERVAL_MIN,
    SOURCE_LAND_STEIERMARK,
    SOURCE_OPEN_METEO,
    SOURCE_SENSOR_COMMUNITY,
)
from .sources.base import AirQualitySource, PollutantSeries, SourceError, SourceResult
from .sources.open_meteo import OpenMeteoSource
from .sources.pollutant_registry import CANONICAL_POLLUTANTS

_LOGGER = logging.getLogger(__name__)


@dataclass
class AirWatchData:
    """Runtime data stored on the config entry: source + analytics coordinators."""

    coordinators: dict[str, AirWatchSourceCoordinator] = field(default_factory=dict)
    analytics: AirWatchAnalyticsCoordinator | None = None


type AirWatchConfigEntry = ConfigEntry[AirWatchData]


def _entry_option(entry: ConfigEntry, key: str, default: Any) -> Any:
    """Read a value preferring options (user-editable) over initial data."""
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


class AirWatchSourceCoordinator(DataUpdateCoordinator[SourceResult]):
    """Fetches one air-quality source on an interval; source-agnostic."""

    config_entry: AirWatchConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: AirWatchConfigEntry,
        source: AirQualitySource,
        source_key: str,
        update_interval_min: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{source_key}",
            config_entry=entry,
            update_interval=timedelta(minutes=update_interval_min),
        )
        self.source = source
        self.source_key = source_key

    async def _async_update_data(self) -> SourceResult:
        session = async_get_clientsession(self.hass)
        try:
            result = await self.source.async_fetch(session=session)
        except SourceError as err:
            raise UpdateFailed(str(err)) from err
        if not result.ok:
            # The location is coverage-checked at setup; a non-OK result now
            # means a transient upstream issue rather than a misconfiguration.
            raise UpdateFailed(
                result.message
                or f"{self.source_key} returned no usable air-quality data."
            )
        return result


def build_coordinators(
    hass: HomeAssistant, entry: AirWatchConfigEntry
) -> dict[str, AirWatchSourceCoordinator]:
    """Construct the per-source coordinators enabled for this entry.

    Open-Meteo is always built (keyless primary). Sensor.Community and Land
    Steiermark are built only when enabled. The global pollutant selection is
    passed to every source, which maps it onto its own capabilities. Secondary
    source clients are imported lazily so a default (Open-Meteo-only) install
    never imports them.
    """
    interval = _entry_option(entry, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MIN)
    pollutants = _entry_option(
        entry, CONF_SELECTED_POLLUTANTS, DEFAULT_SELECTED_POLLUTANTS
    )
    latitude = entry.data[CONF_LATITUDE]
    longitude = entry.data[CONF_LONGITUDE]
    sources_cfg = _entry_option(entry, CONF_SOURCES, {})

    open_meteo = OpenMeteoSource(
        latitude,
        longitude,
        pollutants,
        past_days=OPEN_METEO_PAST_DAYS,
        forecast_days=OPEN_METEO_FORECAST_DAYS,
    )
    coordinators: dict[str, AirWatchSourceCoordinator] = {
        SOURCE_OPEN_METEO: AirWatchSourceCoordinator(
            hass, entry, open_meteo, SOURCE_OPEN_METEO, interval
        )
    }

    sc_cfg = sources_cfg.get(SOURCE_SENSOR_COMMUNITY, {})
    if sc_cfg.get(CONF_ENABLED):
        from .sources.sensor_community import (
            SUPPORTED_POLLUTANTS as SC_POLLUTANTS,
        )
        from .sources.sensor_community import (
            SensorCommunitySource,
        )

        # Sensor.Community is particulate-only; skip building it (and polling the
        # API) when the user selected no PM pollutant — it would have nothing to
        # contribute. A later reload picks it up if PM is added.
        if set(pollutants) & set(SC_POLLUTANTS):
            sensor_community = SensorCommunitySource(
                latitude,
                longitude,
                pollutants,
                stations=sc_cfg.get(CONF_STATIONS) or None,
                max_distance_km=sc_cfg.get(
                    CONF_MAX_DISTANCE_KM, DEFAULT_MAX_DISTANCE_KM
                ),
            )
            coordinators[SOURCE_SENSOR_COMMUNITY] = AirWatchSourceCoordinator(
                hass,
                entry,
                sensor_community,
                SOURCE_SENSOR_COMMUNITY,
                SENSOR_COMMUNITY_UPDATE_INTERVAL_MIN,
            )

    # Land Steiermark: secondary daily-mean source, disabled-by-default until a
    # clean live feed exists (docs/dev/OPEN_QUESTIONS.md Q6).
    ls_cfg = sources_cfg.get(SOURCE_LAND_STEIERMARK, {})
    if ls_cfg.get(CONF_ENABLED):
        from .sources.land_steiermark import LandSteiermarkSource

        land_steiermark = LandSteiermarkSource(
            latitude,
            longitude,
            pollutants,
            station=ls_cfg.get(CONF_STATION) or None,
            max_distance_km=ls_cfg.get(
                CONF_MAX_DISTANCE_KM, LAND_STEIERMARK_MAX_DISTANCE_KM
            ),
        )
        coordinators[SOURCE_LAND_STEIERMARK] = AirWatchSourceCoordinator(
            hass,
            entry,
            land_steiermark,
            SOURCE_LAND_STEIERMARK,
            LAND_STEIERMARK_UPDATE_INTERVAL_MIN,
        )

    return coordinators


@dataclass
class AnalyticsData:
    """Output of the analytics coordinator."""

    # recent_percentile per (source_key, pollutant)
    percentiles: dict[tuple[str, str], PercentileResult] = field(default_factory=dict)
    # cross-source consensus per pollutant
    consensus: dict[str, ConsensusResult] = field(default_factory=dict)


class AirWatchAnalyticsCoordinator(DataUpdateCoordinator[AnalyticsData]):
    """Computes derived analytics from the source coordinators.

    recent_percentile per (source, pollutant) and cross-source consensus per
    pollutant (with its divergence flag). Sources with their own history
    (Open-Meteo's 92-day backfill) compute the percentile from that series;
    sources without one baseline on HA recorder history, emitting
    "insufficient_history" until enough days accrue. Consensus compares each
    source on the common 0/1/2 level scale (EAQI-banded).
    """

    config_entry: AirWatchConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: AirWatchConfigEntry,
        sources: dict[str, AirWatchSourceCoordinator],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_analytics",
            config_entry=entry,
            update_interval=timedelta(hours=1),
        )
        self._sources = sources

    def _source_level(
        self, source_key: str, pollutant: str, series: PollutantSeries
    ) -> int | None:
        """Delegate to analytics.level_for_source (single source of truth)."""
        return level_for_source(source_key, pollutant, series)

    async def _async_update_data(self) -> AnalyticsData:
        today = dt_util.now().date().isoformat()
        percentiles: dict[tuple[str, str], PercentileResult] = {}
        levels: dict[str, dict[str, int]] = {}
        for source_key, coordinator in self._sources.items():
            data = coordinator.data
            if data is None:
                continue
            source = coordinator.source
            # Self-baselining sources rank their own latest day (observation
            # feeds may lag, so the calendar today may be absent).
            ref_day = (data.current_time or today)[:10]
            for pollutant, series in data.pollutants.items():
                if source.supports_history:
                    if source.provides_history_series:
                        percentiles[(source_key, pollutant)] = (
                            recent_percentile_from_series(
                                data.times, series.values, ref_day
                            )
                        )
                    else:
                        percentiles[(source_key, pollutant)] = (
                            await self._recorder_percentile(
                                source_key, pollutant, today
                            )
                        )
                level = self._source_level(source_key, pollutant, series)
                if level is not None:
                    levels.setdefault(pollutant, {})[source_key] = level
        # Pass each pollutant's registry ceiling so the consensus result carries
        # max_possible — the n/m badge denominator on the card.
        consensus_map = {
            p: consensus(src, _registry_max_possible(p))
            for p, src in levels.items()
        }
        return AnalyticsData(percentiles=percentiles, consensus=consensus_map)

    async def _recorder_percentile(
        self, source_key: str, pollutant: str, today: str
    ) -> PercentileResult:
        """recent_percentile from HA recorder history of a source's raw sensor."""
        entity_id = f"sensor.{DOMAIN}_{source_key}_{pollutant}"
        peaks = await self._recorder_daily_peaks(entity_id)
        return compute_recent_percentile(peaks[-PERCENTILE_WINDOW_DAYS:], today)

    async def _recorder_daily_peaks(
        self, entity_id: str
    ) -> list[tuple[str, float]]:
        """Daily peaks of a numeric entity over the trailing window, via recorder.

        Returns an empty list if the recorder is unavailable (→ the caller emits
        "insufficient_history" rather than a misleading number).
        """
        if "recorder" not in self.hass.config.components:
            return []
        from homeassistant.components.recorder import get_instance, history

        end = dt_util.now()
        start = end - timedelta(days=PERCENTILE_WINDOW_DAYS)
        states = await get_instance(self.hass).async_add_executor_job(
            history.state_changes_during_period,
            self.hass,
            start,
            end,
            entity_id,
        )
        times: list[str] = []
        values: list[float] = []
        for state in states.get(entity_id, []):
            try:
                value = float(state.state)
            except (ValueError, TypeError):
                continue  # 'unknown'/'unavailable'
            times.append(dt_util.as_local(state.last_changed).isoformat())
            values.append(value)
        return daily_peaks(times, values)


def analytics_device_info(entry: AirWatchConfigEntry) -> DeviceInfo:
    """Device for the cross-source analytics entities (consensus, divergence)."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_analytics")},
        name=ANALYTICS_DEVICE_NAME,
        manufacturer="AirWatch",
        model="Cross-source analytics",
        entry_type=DeviceEntryType.SERVICE,
    )


def multi_source_pollutants(
    coordinators: dict[str, AirWatchSourceCoordinator],
) -> list[str]:
    """Pollutants currently covered by >= 2 sources (divergence needs two)."""
    counts: dict[str, int] = {}
    for coordinator in coordinators.values():
        if coordinator.data is None:
            continue
        for pollutant in coordinator.data.pollutants:
            counts[pollutant] = counts.get(pollutant, 0) + 1
    return sorted(pollutant for pollutant, n in counts.items() if n >= 2)


def all_covered_pollutants(
    coordinators: dict[str, AirWatchSourceCoordinator],
) -> list[str]:
    """Pollutants currently covered by >= 1 source.

    Single-source pollutants still get a consensus sensor (pass-through level +
    n/m badge); the badge tells users the reading is single-source.
    """
    covered: set[str] = set()
    for coordinator in coordinators.values():
        if coordinator.data is None:
            continue
        covered.update(coordinator.data.pollutants.keys())
    return sorted(covered)


def _registry_max_possible(pollutant: str) -> int:
    """Global source-count ceiling for a pollutant, from the canonical registry.

    The n/m badge on the card uses this as the denominator. Returns 0 for
    pollutants not in the registry (defensive).
    """
    info = CANONICAL_POLLUTANTS.get(pollutant)
    return len(info.sources) if info else 0
