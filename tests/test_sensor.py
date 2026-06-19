"""Decision-verification tests for AirWatch sensor entities (Q3 + Q4).

Full setup over a mocked Open-Meteo endpoint (``aioclient_mock``, host-agnostic
of the query string), then assert the device_class / unit / band-provenance /
state_class contracts on the resulting states. The payload includes pm2_5
(EAQI + WHO + EU bands, pm25 device_class), carbon_monoxide (no EAQI band, no
device_class, ppm convenience attribute) and european_aqi (aqi device_class,
EAQI-only band) so every branch of the registry's banding is exercised.
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


def _payload() -> dict:
    """A realistic multi-day Open-Meteo OK response for the three pollutants."""
    now = dt_util.now().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=1)
    times = [
        (start + timedelta(hours=6 * i)).strftime("%Y-%m-%dT%H:00") for i in range(12)
    ]
    current_time = now.strftime("%Y-%m-%dT%H:00")
    current_vals = {"pm2_5": 12.0, "carbon_monoxide": 250.0, "european_aqi": 30.0}
    hourly = {"time": times}
    current = {"time": current_time}
    units = {}
    for p in _POLLUTANTS:
        base = current_vals[p]
        hourly[p] = [base + (i % 4) for i in range(len(times))]
        current[p] = base
        units[p] = "" if p == "european_aqi" else "µg/m³"
    return {
        "latitude": 48.2,
        "longitude": 16.4,
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
        unique_id="48.2100_16.3700",
        title="AirWatch (48.210, 16.370)",
        data={CONF_LATITUDE: 48.21, CONF_LONGITUDE: 16.37},
        options={
            CONF_SELECTED_POLLUTANTS: _POLLUTANTS,
            CONF_UPDATE_INTERVAL: 60,
            CONF_SOURCES: new_sources_config(),
        },
    )


async def _setup(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(BASE_URL, json=_payload())
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


# --- Q3: device_class + unit + CO ppm convenience -------------------------


async def test_q3_pm25_device_class_and_unit(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    pm = hass.states.get("sensor.airwatch_open_meteo_pm2_5")
    assert pm is not None
    assert pm.attributes["device_class"] == "pm25"
    assert pm.attributes["unit_of_measurement"] == "µg/m³"


async def test_q3_carbon_monoxide_no_device_class_with_ppm(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    co = hass.states.get("sensor.airwatch_open_meteo_carbon_monoxide")
    assert co is not None
    # CO deliberately omits the HA carbon_monoxide device_class (it wants ppm;
    # AirWatch keeps native µg/m³).
    assert co.attributes.get("device_class") is None
    assert co.attributes["unit_of_measurement"] == "µg/m³"
    # ppm is exposed as a tagged convenience attribute, never the state.
    assert isinstance(co.attributes["value_ppm"], float)
    assert isinstance(co.attributes["ppm_conversion_note"], str)


async def test_q3_european_aqi_device_class(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    aqi = hass.states.get("sensor.airwatch_open_meteo_european_aqi")
    assert aqi is not None
    assert aqi.attributes["device_class"] == "aqi"


# --- Q4: band provenance — authorities kept distinct ----------------------


async def test_q4_pm25_bands_carry_all_three_authorities(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    pm = hass.states.get("sensor.airwatch_open_meteo_pm2_5")
    bands = pm.attributes["bands"]
    assert isinstance(bands, dict)
    # Classic + revised index, WHO 2021, and both EU milestones — distinct.
    assert set(bands) == {
        "eaqi_classic", "eaqi_eea_2024", "who_2021", "eu_2024_2881", "eu_2008_50_ec",
    }
    # Index authorities are single band dicts.
    for key in ("eaqi_classic", "eaqi_eea_2024"):
        assert "authority" in bands[key]
        assert "averaging" in bands[key]
    # WHO/EU authorities are lists of per-averaging-window entries.
    for key in ("who_2021", "eu_2024_2881", "eu_2008_50_ec"):
        assert isinstance(bands[key], list) and bands[key]
        for entry in bands[key]:
            assert "authority" in entry
            assert "averaging" in entry
            assert "value" in entry
            assert "exceeds" in entry
    # Normalised level + label are present.
    assert "level" in pm.attributes
    assert "level_label" in pm.attributes


async def test_q4_carbon_monoxide_bands_omit_eaqi(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    co = hass.states.get("sensor.airwatch_open_meteo_carbon_monoxide")
    bands = co.attributes["bands"]
    assert isinstance(bands, dict)
    # CO is not part of either EAQI; it carries WHO (2021 + retained) + EU bands.
    assert "eaqi_classic" not in bands and "eaqi_eea_2024" not in bands
    assert set(bands) == {
        "who_2021", "who_retained", "eu_2024_2881", "eu_2008_50_ec",
    }
    assert "level" in co.attributes
    assert "level_label" in co.attributes


async def test_q4_european_aqi_bands_only_eaqi(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    aqi = hass.states.get("sensor.airwatch_open_meteo_european_aqi")
    bands = aqi.attributes["bands"]
    assert isinstance(bands, dict)
    # The index has no µg/m³ WHO/EU guideline and no revised-index value — classic only.
    assert set(bands) == {"eaqi_classic"}
    assert "authority" in bands["eaqi_classic"]
    assert "averaging" in bands["eaqi_classic"]
    assert "level" in aqi.attributes
    assert "level_label" in aqi.attributes


# --- state_class -----------------------------------------------------------


async def test_raw_sensors_are_measurement_state_class(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    for pollutant in _POLLUTANTS:
        state = hass.states.get(f"sensor.airwatch_open_meteo_{pollutant}")
        assert state is not None
        # CO has no device_class but still declares MEASUREMENT for statistics.
        assert state.attributes["state_class"] == "measurement"


# --- consensus -------------------------------------------------------------


async def test_consensus_sensor_has_source_count_badge(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    consensus = hass.states.get("sensor.airwatch_analytics_pm2_5_consensus")
    assert consensus is not None
    assert consensus.attributes["source_count"] == 1
    assert "max_possible_sources" in consensus.attributes
