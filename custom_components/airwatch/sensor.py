"""Sensor entities for AirWatch.

One sensor per (source, pollutant) pair. State is the current value in the
source's native units (µg/m³ for concentrations, dimensionless for the
european_aqi index); the daily-peak forecast and band provenance live in
attributes. Entities sit under a per-source device and are named so their
entity IDs slug to ``sensor.airwatch_<source>_<pollutant>``.

Adapted from PollenWatch ``sensor.py``: allergen/species → pollutant
throughout, PollenWatch's per-source categorical scales → AirWatch's
per-pollutant ``device_class`` + µg/m³ units read from the canonical pollutant
registry. The personal_score sensor is dropped for v1. Band provenance is
*exposed* on each raw sensor's attributes rather than asserted (OPEN_QUESTIONS
Q4): the EAQI band + its authority, the WHO 2021 overlay (with its
averaging-period caveat), and the normalised 0/1/2 level.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .analytics import (
    CONSENSUS_OPTIONS,
    daily_peaks,
    level_for_source,
)
from .analytics import (
    level_label as _level_label,
)
from .const import (
    ATTR_BAND_AUTHORITY,
    ATTR_BAND_AVERAGING,
    ATTR_CO_PPM,
    ATTR_CO_PPM_NOTE,
    ATTR_EAQI_BAND,
    ATTR_FORECAST,
    ATTR_GRID_SHIFT_KM,
    ATTR_LAST_UPDATED,
    ATTR_LEVEL,
    ATTR_LEVEL_LABEL,
    ATTR_MAX_SOURCES,
    ATTR_REQUESTED_LAT,
    ATTR_REQUESTED_LON,
    ATTR_SNAPPED_LAT,
    ATTR_SNAPPED_LON,
    ATTR_SOURCE_COUNT,
    ATTR_STATION,
    ATTRIBUTION_CAMS,
    DOMAIN,
    FORECAST_DAYS,
    POLLUTANT_NAMES,
    SOURCE_ATTRIBUTIONS,
    SOURCE_CONFIG_URLS,
    SOURCE_DEVICE_MODELS,
    SOURCE_DEVICE_NAMES,
)
from .coordinator import (
    AirWatchAnalyticsCoordinator,
    AirWatchConfigEntry,
    AirWatchSourceCoordinator,
    all_covered_pollutants,
    analytics_device_info,
)
from .sources.pollutant_registry import (
    CANONICAL_POLLUTANTS,
    CO_PPM_NOTE,
    BandAuthority,
    co_ugm3_to_ppm,
    eaqi_band_for,
    eaqi_band_label,
    who_assessment_for,
)

# Coordinator-driven entities with no per-entity writes — HA serialization
# is unnecessary; declare parallel updates to keep the silver rule explicit.
PARALLEL_UPDATES = 0

# All possible per-source slugs the integration could ever have created
# entities under. Used to prune entities for sources that have been DISABLED
# via the options flow (those sources stop being built into coordinators, so
# the per-coordinator pruning loop never reaches them — without this catch
# they orphan as ``unavailable`` forever).
ALL_KNOWN_SOURCES: set[str] = set(SOURCE_DEVICE_NAMES.keys())

# Extra-state-attribute keys for the recent_percentile sensor.
ATTR_HISTORY_STATUS = "history_status"
ATTR_DAYS_OF_HISTORY = "days_of_history"
# ... and the consensus sensor.
ATTR_SOURCE_LEVELS = "source_levels"
# WHO overlay attribute keys (Q4 — health overlay, not a verdict).
ATTR_WHO_EXCEEDS = "who_exceeds"
ATTR_WHO_GUIDELINE = "who_guideline"

# The classic-EEA/Open-Meteo bands AirWatch derives are authored by the EAQI.
_BAND_AUTHORITY = BandAuthority.EAQI.value


def _pollutant_name(pollutant: str) -> str:
    """Human-readable name for a pollutant key (registry, then title-cased)."""
    return POLLUTANT_NAMES.get(pollutant, pollutant.replace("_", " ").title())


def _source_device_info(entry: AirWatchConfigEntry, source_key: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_{source_key}")},
        name=SOURCE_DEVICE_NAMES[source_key],
        manufacturer="AirWatch",
        model=SOURCE_DEVICE_MODELS.get(source_key),
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=SOURCE_CONFIG_URLS.get(source_key),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AirWatchConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AirWatch sensors for a config entry.

    Runs on every reload (including after an options change), so it also prunes
    registry entries for pollutants no longer configured for each source.
    """
    runtime = entry.runtime_data
    analytics = runtime.analytics
    entities: list[SensorEntity] = []
    for source_key, coordinator in runtime.coordinators.items():
        # Keep registry entries for every configured pollutant (so a transient
        # absence doesn't delete a sensor); only create sensors for pollutants the
        # source actually returned (a source's set is location/coverage-dependent).
        configured = set(coordinator.source.pollutants)
        _async_remove_deconfigured_entities(hass, entry, source_key, configured)
        if coordinator.data is None:
            continue
        present = [
            p for p in coordinator.source.pollutants if p in coordinator.data.pollutants
        ]
        for pollutant in present:
            entities.append(AirWatchSensor(coordinator, source_key, pollutant))
            # recent_percentile only for sources whose data may be baselined
            # (supports_history). A no-storage source would skip it cleanly.
            if analytics is not None and coordinator.source.supports_history:
                entities.append(
                    RecentPercentileSensor(analytics, entry, source_key, pollutant)
                )

    # Prune entities for sources that are no longer enabled — disabling a
    # source via the options flow stops it being built into a coordinator, so
    # the per-coordinator loop above never runs the prune for it. Without this
    # catch the disabled source's sensors live on as ``unavailable`` forever.
    active_sources = set(runtime.coordinators.keys())
    for source_key in ALL_KNOWN_SOURCES:
        if source_key not in active_sources:
            _async_remove_deconfigured_entities(hass, entry, source_key, set())

    # Cross-source consensus: one per pollutant that >= 1 source currently
    # covers. Single-source pollutants emit a pass-through consensus + n/m=1/x
    # badge; the badge tells the user it's single-source, not the sensor's
    # absence. DivergenceSensor (binary) still requires >= 2 — gated separately
    # in binary_sensor.py.
    covered_pollutants: list[str] = []
    if analytics is not None:
        covered_pollutants = all_covered_pollutants(runtime.coordinators)
        for pollutant in covered_pollutants:
            entities.append(ConsensusSensor(analytics, entry, pollutant))

    # Prune stale consensus sensors for pollutants no longer covered (e.g. user
    # disabled the only source covering a pollutant). Same orphan story as
    # above, applied to the analytics device.
    _async_remove_orphan_analytics(hass, entry, set(covered_pollutants), "consensus")

    async_add_entities(entities)


@callback
def _async_remove_orphan_analytics(
    hass: HomeAssistant,
    entry: AirWatchConfigEntry,
    active_pollutants: set[str],
    metric: str,
) -> None:
    """Remove analytics entities (consensus / divergence) for pollutants no
    longer covered. Shared by sensor.py + binary_sensor.py.
    """
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_{metric}_"
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.unique_id.startswith(prefix):
            pollutant = reg_entry.unique_id[len(prefix):]
            if pollutant not in active_pollutants:
                registry.async_remove(reg_entry.entity_id)


@callback
def _async_remove_deconfigured_entities(
    hass: HomeAssistant,
    entry: AirWatchConfigEntry,
    source_key: str,
    configured: set[str],
) -> None:
    """Remove a source's sensor entities for pollutants no longer configured.

    Without this, deselecting a pollutant in the options flow would leave the
    sensor lingering as ``unavailable`` in the registry instead of disappearing.
    """
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_{source_key}_"
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.unique_id.startswith(prefix):
            # Suffix is "<pollutant>" or "<pollutant>_<metric>" (e.g.
            # pm2_5_recent_percentile). The pollutant is the leading token, but
            # pollutant keys themselves contain underscores (pm2_5,
            # nitrogen_dioxide), so match against the configured set rather than
            # splitting blindly.
            suffix = reg_entry.unique_id[len(prefix):]
            pollutant = _pollutant_from_suffix(suffix, configured)
            if pollutant not in configured:
                registry.async_remove(reg_entry.entity_id)


def _pollutant_from_suffix(suffix: str, configured: set[str]) -> str:
    """Recover the pollutant key from a unique-id suffix.

    Suffixes are ``<pollutant>`` or ``<pollutant>_<metric>``. Pollutant keys
    contain underscores (``pm2_5``, ``nitrogen_dioxide``), so a blind split is
    wrong; longest configured key that prefixes the suffix wins, falling back to
    the bare suffix so unknown entities still prune.
    """
    for pollutant in sorted(configured, key=len, reverse=True):
        if suffix == pollutant or suffix.startswith(f"{pollutant}_"):
            return pollutant
    return suffix


def _forecast_attr(
    times: list[str], values: list[float | None], today: str, max_days: int
) -> list[dict[str, Any]]:
    """The upcoming daily-peak forecast: per-day max for dates >= today.

    The series spans ~92 past days (for recent_percentile), so the forecast must
    be the today-onward slice — not the earliest days. Peaks (not means) are the
    health-relevant exposure; the partially-null final day is dropped via
    max_days.
    """
    return [
        {"date": date, "value": peak}
        for date, peak in daily_peaks(times, values)
        if date >= today
    ][:max_days]


class AirWatchSensor(CoordinatorEntity[AirWatchSourceCoordinator], SensorEntity):
    """Current concentration (or index) for one pollutant from one source.

    device_class + unit come from the canonical pollutant registry (Q3): the
    µg/m³ concentration classes (``pm25``, ``pm10``, …) for the mass pollutants,
    ``aqi`` for european_aqi, and **no** device_class for carbon_monoxide (HA's
    ``carbon_monoxide`` class wants ppm; AirWatch keeps the source's native
    µg/m³). Every raw sensor declares ``state_class = MEASUREMENT`` so CO still
    gets long-term statistics without a device_class.
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:air-filter"

    def __init__(
        self,
        coordinator: AirWatchSourceCoordinator,
        source_key: str,
        pollutant: str,
    ) -> None:
        super().__init__(coordinator)
        self._pollutant = pollutant
        self._source_key = source_key
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{source_key}_{pollutant}"
        self._attr_translation_key = pollutant
        # Fallback name (used if no strings.json translation exists for the
        # pollutant). Without this, HA can't slugify the entity_id past the
        # device prefix and entities collide on the bare device id.
        self._attr_name = _pollutant_name(pollutant)
        # Force entity_id to match the canonical pollutant registry key so it
        # agrees with coordinator._recorder_percentile, which looks up
        # sensor.{DOMAIN}_{source_key}_{pollutant}. HA preserves existing
        # entity_ids by unique_id, so re-slugging here is non-breaking.
        self.entity_id = f"sensor.{DOMAIN}_{source_key}_{pollutant}"
        self._attr_attribution = SOURCE_ATTRIBUTIONS.get(source_key, ATTRIBUTION_CAMS)
        # Per-pollutant device_class + unit from the registry (Q3). device_class
        # is a string or None; map non-None onto SensorDeviceClass. CO → None.
        info = CANONICAL_POLLUTANTS[pollutant]
        self._attr_device_class = (
            SensorDeviceClass(info.device_class)
            if info.device_class is not None
            else None
        )
        self._attr_native_unit_of_measurement = info.unit
        self._attr_device_info = _source_device_info(entry, source_key)

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._pollutant in self.coordinator.data.pollutants
        )

    @property
    def native_value(self) -> float | None:
        series = self.coordinator.data.pollutants.get(self._pollutant)
        return series.current if series else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        result = self.coordinator.data
        series = result.pollutants.get(self._pollutant)
        if series is None:
            return None
        shift = result.coordinate_shift_km
        today = (result.current_time or "")[:10]
        current = series.current
        # Normalised severity from the integration's own bucketing
        # (analytics.level_for_source — single source of truth for every
        # downstream consumer). Band provenance is exposed, not asserted (Q4).
        lvl = level_for_source(self._source_key, self._pollutant, series)
        band = eaqi_band_for(self._pollutant, current)
        attrs: dict[str, Any] = {
            ATTR_FORECAST: _forecast_attr(
                result.times, series.values, today, FORECAST_DAYS
            ),
            ATTR_LEVEL: lvl,
            ATTR_LEVEL_LABEL: _level_label(lvl),
            ATTR_EAQI_BAND: eaqi_band_label(band),
            ATTR_BAND_AUTHORITY: _BAND_AUTHORITY,
            ATTR_REQUESTED_LAT: result.requested_lat,
            ATTR_REQUESTED_LON: result.requested_lon,
            ATTR_SNAPPED_LAT: result.snapped_lat,
            ATTR_SNAPPED_LON: result.snapped_lon,
            ATTR_GRID_SHIFT_KM: round(shift, 2) if shift is not None else None,
            ATTR_LAST_UPDATED: result.generated_at,
        }
        # WHO 2021 health overlay — surfaced WITH its averaging-period caveat
        # (AirWatch readings are hourly; WHO values are 24-hour/8-hour/annual
        # means). Skipped when no guideline exists (european_aqi).
        who = who_assessment_for(self._pollutant, current)
        if who is not None:
            attrs[ATTR_WHO_EXCEEDS] = who.exceeds
            attrs[ATTR_WHO_GUIDELINE] = who.guideline
            attrs[ATTR_BAND_AVERAGING] = who.averaging
        # CO convenience: expose a tagged ppm value + its conversion note (Q3).
        # The state stays the native µg/m³; ppm is never the state.
        if self._pollutant == "carbon_monoxide":
            attrs[ATTR_CO_PPM] = co_ugm3_to_ppm(current)
            attrs[ATTR_CO_PPM_NOTE] = CO_PPM_NOTE
        if series.native is not None:
            # Source's native categorical value (e.g. a daily-mean band).
            attrs["native_value"] = series.native
        if result.station is not None:
            # Station-based sources (Sensor.Community, Land Steiermark).
            attrs[ATTR_STATION] = result.station
        return attrs


class ConsensusSensor(
    CoordinatorEntity[AirWatchAnalyticsCoordinator], SensorEntity
):
    """Cross-source consensus level for one pollutant (good/elevated/high/mixed).

    Categorical (ENUM) so it can report "mixed" when sources disagree by >1
    level. Also created for single-source pollutants (pass-through level +
    source_count=1). The card uses ``source_count`` / ``max_possible_sources``
    to render the n/m badge — the honesty mechanism that signals single-source
    vs cross-validated readings.
    """

    # Device-scoped entity ID: HA prefixes device-associated entities with the
    # device slug, so the ID is sensor.airwatch_analytics_<pollutant>_consensus.
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = CONSENSUS_OPTIONS
    _attr_icon = "mdi:scale-balance"

    def __init__(
        self,
        coordinator: AirWatchAnalyticsCoordinator,
        entry: AirWatchConfigEntry,
        pollutant: str,
    ) -> None:
        super().__init__(coordinator)
        self._pollutant = pollutant
        self._attr_unique_id = f"{entry.entry_id}_consensus_{pollutant}"
        self._attr_translation_key = f"consensus_{pollutant}"
        self._attr_name = f"{_pollutant_name(pollutant)} consensus"
        # Canonical-key entity_id (see AirWatchSensor for rationale).
        self.entity_id = f"sensor.{DOMAIN}_analytics_{pollutant}_consensus"
        self._attr_device_info = analytics_device_info(entry)

    def _result(self):
        return self.coordinator.data.consensus.get(self._pollutant)

    @property
    def available(self) -> bool:
        # Available when at least one source is currently contributing. The
        # n/m badge in attributes tells the user whether it's single-source or
        # cross-validated; the sensor's presence is no longer the gate.
        result = self._result()
        return (
            super().available
            and result is not None
            and result.source_count >= 1
        )

    @property
    def native_value(self) -> str | None:
        result = self._result()
        return result.state if result else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        result = self._result()
        if result is None:
            return None
        return {
            ATTR_LEVEL: result.level,
            ATTR_LEVEL_LABEL: _level_label(result.level),
            ATTR_SOURCE_LEVELS: result.source_levels,
            ATTR_SOURCE_COUNT: result.source_count,
            ATTR_MAX_SOURCES: result.max_possible,
        }


class RecentPercentileSensor(
    CoordinatorEntity[AirWatchAnalyticsCoordinator], SensorEntity
):
    """Today's daily peak as a percentile of the recent window (per source).

    Single-source (each source gets its own). Open-Meteo computes from its
    92-day backfill (day one); a recorder-baselined source reports an honest
    "insufficient_history" state (no number) until enough days accrue. State is
    unitless 0–100; the history status is in attributes.
    """

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-bell-curve-cumulative"
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: AirWatchAnalyticsCoordinator,
        entry: AirWatchConfigEntry,
        source_key: str,
        pollutant: str,
    ) -> None:
        super().__init__(coordinator)
        self._key = (source_key, pollutant)
        self._attr_unique_id = (
            f"{entry.entry_id}_{source_key}_{pollutant}_recent_percentile"
        )
        self._attr_translation_key = f"recent_percentile_{pollutant}"
        self._attr_name = f"{_pollutant_name(pollutant)} recent percentile"
        # Canonical-key entity_id (see AirWatchSensor for rationale).
        self.entity_id = (
            f"sensor.{DOMAIN}_{source_key}_{pollutant}_recent_percentile"
        )
        self._attr_device_info = _source_device_info(entry, source_key)

    @property
    def native_value(self) -> float | None:
        result = self.coordinator.data.percentiles.get(self._key)
        if result is None or result.status != "ok":
            return None
        return result.percentile

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        result = self.coordinator.data.percentiles.get(self._key)
        if result is None:
            return None
        return {
            ATTR_HISTORY_STATUS: result.status,
            ATTR_DAYS_OF_HISTORY: result.days,
        }
