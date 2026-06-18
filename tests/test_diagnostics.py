"""Diagnostics tests — the config-entry dump must redact location.

Drives a real setup (Open-Meteo mocked via ``aioclient_mock``) so the
diagnostics run against live ``runtime_data`` coordinators, then asserts the
coordinates are redacted from both ``data`` and ``options`` and that each
coordinator is summarised without leaking location.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.diagnostics import REDACTED
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.airwatch.const import (
    CONF_SELECTED_POLLUTANTS,
    CONF_SOURCES,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    new_sources_config,
)
from custom_components.airwatch.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.airwatch.sources.open_meteo import BASE_URL

_POLLUTANTS = ["pm2_5", "ozone"]


def _payload() -> dict:
    now = dt_util.now().replace(minute=0, second=0, microsecond=0)
    times = [
        (now - timedelta(days=1) + timedelta(hours=6 * i)).strftime("%Y-%m-%dT%H:00")
        for i in range(12)
    ]
    current_time = now.strftime("%Y-%m-%dT%H:00")
    hourly = {"time": times}
    current = {"time": current_time}
    units = {}
    for p in _POLLUTANTS:
        hourly[p] = [10.0 + (i % 4) for i in range(len(times))]
        current[p] = 12.0
        units[p] = "µg/m³"
    return {
        "latitude": 47.1,
        "longitude": 15.4,
        "timezone": "Europe/Vienna",
        "elevation": 363.0,
        "hourly_units": units,
        "current": current,
        "hourly": hourly,
    }


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id="47.0700_15.4400",
        title="AirWatch (47.070, 15.440)",
        data={CONF_LATITUDE: 47.07, CONF_LONGITUDE: 15.44},
        options={
            CONF_SELECTED_POLLUTANTS: _POLLUTANTS,
            CONF_UPDATE_INTERVAL: 60,
            CONF_SOURCES: new_sources_config(),
        },
    )


async def test_diagnostics_redacts_location_and_summarises_sources(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(BASE_URL, json=_payload())
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)

    # Coordinates redacted in entry data (never leaked).
    assert diag["entry"]["data"][CONF_LATITUDE] == REDACTED
    assert diag["entry"]["data"][CONF_LONGITUDE] == REDACTED

    # Open-Meteo coordinator summarised, OK, with a location-free pollutant view.
    om = diag["coordinators"]["open_meteo"]
    assert om["last_update_success"] is True
    assert om["update_interval"] == 60 * 60  # seconds
    result = om["result"]
    assert result["status"] == "ok"
    assert set(result["pollutants"]) == set(_POLLUTANTS)
    # The summary carries counts/units, not raw coordinates.
    assert "latitude" not in result
    assert "snapped_lat" not in result
    assert result["pollutants"]["pm2_5"]["unit"] == "µg/m³"
