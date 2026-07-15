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

from .const import CONF_STATION, CONF_STATIONS
from .coordinator import AirWatchConfigEntry
from .sources.base import SourceResult

# Station identifiers are location-equivalent: a Sensor.Community sensor id or a
# Land Steiermark station label (which also carries the exact distance from the
# user's coordinates) both resolve to public coordinates, undoing the lat/lon
# redaction. Redact them alongside the coordinates.
TO_REDACT = {CONF_LATITUDE, CONF_LONGITUDE, CONF_STATION, CONF_STATIONS}


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
        # Do NOT emit result.station (station id / label + exact distance) — it
        # re-identifies the user's location. A presence flag keeps the debugging
        # value (was a station selected?) without the identifier.
        "station_selected": result.station is not None,
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
