"""Binary sensors for AirWatch — cross-source divergence.

divergence is the boolean companion to consensus's "mixed": on when the sources
disagree by more than one level for a pollutant. Lives under the same "AirWatch
Analytics" device as consensus, and is unavailable when fewer than two sources
currently cover the pollutant (it never flags divergence from a single source).

Ported ~as-is from PollenWatch ``binary_sensor.py`` (species → pollutant).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, POLLUTANT_NAMES
from .coordinator import (
    AirWatchAnalyticsCoordinator,
    AirWatchConfigEntry,
    analytics_device_info,
    multi_source_pollutants,
)

# Coordinator-driven entities with no per-entity writes — HA serialization
# is unnecessary; declare parallel updates to keep the silver rule explicit.
PARALLEL_UPDATES = 0

ATTR_SOURCE_LEVELS = "source_levels"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AirWatchConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the divergence binary sensors (one per multi-source pollutant)."""
    from .sensor import _async_remove_orphan_analytics

    runtime = entry.runtime_data
    analytics = runtime.analytics
    if analytics is None:
        _async_remove_orphan_analytics(hass, entry, set(), "divergence")
        return
    pollutant_list = multi_source_pollutants(runtime.coordinators)
    # Prune divergence binary sensors for pollutants that dropped below the
    # 2-source threshold (mirrors the consensus pruning in sensor.py).
    _async_remove_orphan_analytics(hass, entry, set(pollutant_list), "divergence")
    async_add_entities(
        DivergenceSensor(analytics, entry, pollutant)
        for pollutant in pollutant_list
    )


class DivergenceSensor(
    CoordinatorEntity[AirWatchAnalyticsCoordinator], BinarySensorEntity
):
    """True when sources disagree by more than one level for a pollutant."""

    # Device-scoped entity ID (see ConsensusSensor): HA prefixes with the device
    # slug -> binary_sensor.airwatch_analytics_<pollutant>_divergence.
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:call-split"

    def __init__(
        self,
        coordinator: AirWatchAnalyticsCoordinator,
        entry: AirWatchConfigEntry,
        pollutant: str,
    ) -> None:
        super().__init__(coordinator)
        self._pollutant = pollutant
        self._attr_unique_id = f"{entry.entry_id}_divergence_{pollutant}"
        self._attr_translation_key = f"divergence_{pollutant}"
        self._attr_name = (
            f"{POLLUTANT_NAMES.get(pollutant, pollutant)} divergence"
        )
        # Canonical-key entity_id — one rule across all pollutants so users
        # iterating programmatically don't need a translation table.
        self.entity_id = f"binary_sensor.{DOMAIN}_analytics_{pollutant}_divergence"
        self._attr_device_info = analytics_device_info(entry)

    def _result(self):
        return self.coordinator.data.consensus.get(self._pollutant)

    @property
    def available(self) -> bool:
        result = self._result()
        return (
            super().available
            and result is not None
            and len(result.source_levels) >= 2
        )

    @property
    def is_on(self) -> bool | None:
        result = self._result()
        return result.diverged if result else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        result = self._result()
        if result is None:
            return None
        return {ATTR_SOURCE_LEVELS: result.source_levels}
