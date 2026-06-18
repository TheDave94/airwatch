"""End-to-end setup tests: config entry -> coordinators -> sensors -> unload.

The Open-Meteo HTTP endpoint is mocked host-agnostic of the query string via the
``aioclient_mock`` fixture, so the full integration wiring runs for real: the
source builds its URL and GETs it, the per-source coordinator's first refresh
parses the response, the analytics coordinator derives consensus, and the sensor
platform creates entities. A 400 error body exercises the SETUP_RETRY path.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
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
from custom_components.airwatch.sources.open_meteo import BASE_URL

_POLLUTANTS = ["pm2_5", "carbon_monoxide", "european_aqi"]


def _payload(pollutants: list[str] | None = None) -> dict:
    """A realistic multi-day Open-Meteo air-quality OK response.

    Times are anchored to "now" so the today-onward daily-peak forecast and the
    self-baselined recent_percentile have data to work with. Each requested
    variable appears in ``current`` and in the ``hourly`` block aligned to the
    ``hourly.time`` axis.
    """
    pollutants = pollutants or _POLLUTANTS
    now = dt_util.now().replace(minute=0, second=0, microsecond=0)
    # 3 days of 6-hourly samples spanning yesterday..tomorrow.
    start = now - timedelta(days=1)
    times = [
        (start + timedelta(hours=6 * i)).strftime("%Y-%m-%dT%H:00") for i in range(12)
    ]
    current_time = now.strftime("%Y-%m-%dT%H:00")
    # Per-pollutant constant current value + a varied hourly series.
    current_vals = {
        "pm2_5": 12.0,
        "pm10": 22.0,
        "nitrogen_dioxide": 35.0,
        "ozone": 60.0,
        "sulphur_dioxide": 8.0,
        "carbon_monoxide": 250.0,
        "european_aqi": 30.0,
    }
    hourly = {"time": times}
    current = {"time": current_time}
    units = {}
    for p in pollutants:
        base = current_vals.get(p, 10.0)
        hourly[p] = [base + (i % 4) for i in range(len(times))]
        current[p] = base
        units[p] = "" if p == "european_aqi" else "µg/m³"
    return {
        "latitude": 47.1,
        "longitude": 15.4,
        "timezone": "Europe/Vienna",
        "elevation": 363.0,
        "hourly_units": units,
        "current": current,
        "hourly": hourly,
    }


def _entry(pollutants: list[str] | None = None) -> MockConfigEntry:
    pollutants = pollutants or _POLLUTANTS
    return MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id="47.0700_15.4400",
        title="AirWatch (47.070, 15.440)",
        data={CONF_LATITUDE: 47.07, CONF_LONGITUDE: 15.44},
        options={
            CONF_SELECTED_POLLUTANTS: pollutants,
            CONF_UPDATE_INTERVAL: 60,
            CONF_SOURCES: new_sources_config(),
        },
    )


async def test_setup_loads_and_creates_sensors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A covered entry loads and creates the per-source raw sensors."""
    aioclient_mock.get(BASE_URL, json=_payload())
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    pm = hass.states.get("sensor.airwatch_open_meteo_pm2_5")
    assert pm is not None
    assert float(pm.state) == 12.0
    assert hass.states.get("sensor.airwatch_open_meteo_carbon_monoxide") is not None
    assert hass.states.get("sensor.airwatch_open_meteo_european_aqi") is not None
    # Self-baselined recent_percentile entity exists (Open-Meteo backfill).
    assert (
        hass.states.get("sensor.airwatch_open_meteo_pm2_5_recent_percentile")
        is not None
    )


async def test_unload_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Unloading a loaded entry transitions it to NOT_LOADED."""
    aioclient_mock.get(BASE_URL, json=_payload())
    entry = _entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_first_refresh_failure_sets_retry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An out-of-coverage (HTTP 400) first refresh leaves the entry in retry.

    Open-Meteo is the primary, blocking source: a non-OK first refresh raises
    ConfigEntryNotReady, so the entry lands in SETUP_RETRY rather than LOADED.
    """
    aioclient_mock.get(
        BASE_URL,
        status=400,
        json={"error": True, "reason": "No data is available for this location"},
    )
    entry = _entry()
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
