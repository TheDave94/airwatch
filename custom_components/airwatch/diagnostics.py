"""Diagnostics support for AirWatch.

Dumps the config entry's data + options (with the location coordinates
redacted) plus a per-coordinator summary of each source's last fetch result.
Ported from PollenWatch's diagnostics shape.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant

from .coordinator import AirWatchConfigEntry
from .sources.base import SourceResult

TO_REDACT = {CONF_LATITUDE, CONF_LONGITUDE}


def _summarise_result(result: SourceResult | None) -> dict[str, Any] | None:
    """Compact, location-free summary of a source's last fetch result."""
    if result is None:
        return None
    return {
        "source": result.source,
        "status": result.status.value,
        "timezone": result.timezone,
        "current_time": result.current_time,
        "generated_at": result.generated_at,
        "station": result.station,
        "coordinate_shift_km": result.coordinate_shift_km,
        "times": len(result.times),
        "pollutants": {
            key: {
                "unit": series.unit,
                "current": series.current,
                "values": len(series.values),
            }
            for key, series in result.pollutants.items()
        },
        "message": result.message,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AirWatchConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry (location redacted)."""
    data = entry.runtime_data
    coordinators = data.coordinators if data else {}
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "coordinators": {
            source_key: {
                "last_update_success": coordinator.last_update_success,
                "update_interval": (
                    coordinator.update_interval.total_seconds()
                    if coordinator.update_interval
                    else None
                ),
                "result": _summarise_result(coordinator.data),
            }
            for source_key, coordinator in coordinators.items()
        },
    }
