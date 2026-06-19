"""Two-source integration: Open-Meteo + Sensor.Community → consensus/divergence.

The whole point of a second source: cross-source consensus and the divergence
flag finally have two real inputs to compare. This sets up both sources (each
HTTP endpoint mocked) and asserts the analytics entities light up — consensus
counts 2 sources and divergence flags a >1-level disagreement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.airwatch.const import (
    CONF_ENABLED,
    CONF_MAX_DISTANCE_KM,
    CONF_SELECTED_POLLUTANTS,
    CONF_SOURCES,
    CONF_STATIONS,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    SOURCE_LAND_STEIERMARK,
    SOURCE_OPEN_METEO,
    SOURCE_SENSOR_COMMUNITY,
)
from custom_components.airwatch.sources.open_meteo import BASE_URL as OM_URL

_POLLUTANTS = ["pm2_5", "pm10"]
_SC_STATION = 45690
_SC_URL = f"https://data.sensor.community/airrohr/v1/sensor/{_SC_STATION}/"


def _om_payload() -> dict:
    """Open-Meteo OK payload. pm2_5 current 12 → revised EEA band 2 → level 0 (good)."""
    now = dt_util.now().replace(minute=0, second=0, microsecond=0)
    times = [
        (now - timedelta(days=1) + timedelta(hours=6 * i)).strftime("%Y-%m-%dT%H:00")
        for i in range(12)
    ]
    current_time = now.strftime("%Y-%m-%dT%H:00")
    hourly = {"time": times}
    current = {"time": current_time}
    units = {}
    for p, val in (("pm2_5", 12.0), ("pm10", 20.0)):
        hourly[p] = [val for _ in times]
        current[p] = val
        units[p] = "µg/m³"
    return {
        "latitude": 47.1, "longitude": 15.4, "timezone": "Europe/Vienna",
        "elevation": 363.0, "hourly_units": units, "current": current,
        "hourly": hourly,
    }


def _sc_payload() -> list[dict]:
    """Sensor.Community station reading. pm2_5 120 → revised EEA band 5 → level 2.

    Two levels above Open-Meteo's level 0 → consensus 'mixed' + divergence on.
    (Under the revised index pm2_5 must be ≥91 for level 2; 120 lands in the
    "very poor" 91–140 band.)
    """
    ts = (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    return [
        {
            "timestamp": ts,
            "location": {"latitude": "47.07", "longitude": "15.44"},
            "sensor": {"id": _SC_STATION, "sensor_type": {"name": "SDS011"}},
            "sensordatavalues": [
                {"value_type": "P1", "value": "85.0"},
                {"value_type": "P2", "value": "120.0"},
            ],
        }
    ]


def _entry() -> MockConfigEntry:
    sources = {
        SOURCE_OPEN_METEO: {CONF_ENABLED: True},
        SOURCE_SENSOR_COMMUNITY: {
            CONF_ENABLED: True,
            CONF_MAX_DISTANCE_KM: 10.0,
            CONF_STATIONS: [_SC_STATION],
        },
        SOURCE_LAND_STEIERMARK: {CONF_ENABLED: False, "station": ""},
    }
    return MockConfigEntry(
        domain=DOMAIN, version=1, unique_id="47.0700_15.4400",
        title="AirWatch (47.070, 15.440)",
        data={CONF_LATITUDE: 47.07, CONF_LONGITUDE: 15.44},
        options={
            CONF_SELECTED_POLLUTANTS: _POLLUTANTS,
            CONF_UPDATE_INTERVAL: 60,
            CONF_SOURCES: sources,
        },
    )


async def test_two_sources_drive_consensus_and_divergence(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(OM_URL, json=_om_payload())
    aioclient_mock.get(_SC_URL, json=_sc_payload())

    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    # Both sources produced a raw pm2_5 sensor.
    om_pm = hass.states.get("sensor.airwatch_open_meteo_pm2_5")
    sc_pm = hass.states.get("sensor.airwatch_sensor_community_pm2_5")
    assert om_pm is not None and float(om_pm.state) == 12.0
    assert sc_pm is not None and float(sc_pm.state) == 120.0
    # Sensor.Community carries the fault-rejected station count.
    assert sc_pm.attributes.get("native_value") == "1 station(s)"

    # Consensus now spans TWO sources for pm2_5.
    consensus = hass.states.get("sensor.airwatch_analytics_pm2_5_consensus")
    assert consensus is not None
    assert consensus.attributes["source_count"] == 2
    assert consensus.attributes["max_possible_sources"] == 3  # OM + SC + LS globally
    # level 0 (OM) vs level 2 (SC) → >1 apart → mixed.
    assert consensus.state == "mixed"
    assert set(consensus.attributes["source_levels"]) == {
        SOURCE_OPEN_METEO,
        SOURCE_SENSOR_COMMUNITY,
    }

    # Divergence binary sensor exists (>=2 sources) and is ON (spread > 1 level).
    divergence = hass.states.get("binary_sensor.airwatch_analytics_pm2_5_divergence")
    assert divergence is not None
    assert divergence.state == "on"


async def test_consensus_agrees_when_sources_align(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Sanity counterpoint: aligned readings → agreement, divergence off."""
    om = _om_payload()  # pm2_5 = 12 → level 0
    sc = _sc_payload()
    # Make the SC station read pm2_5 = 8 (level 0) too → agreement.
    sc[0]["sensordatavalues"] = [
        {"value_type": "P1", "value": "15.0"},
        {"value_type": "P2", "value": "8.0"},
    ]
    aioclient_mock.get(OM_URL, json=om)
    aioclient_mock.get(_SC_URL, json=sc)

    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    consensus = hass.states.get("sensor.airwatch_analytics_pm2_5_consensus")
    assert consensus.attributes["source_count"] == 2
    assert consensus.state == "good"  # both level 0
    divergence = hass.states.get("binary_sensor.airwatch_analytics_pm2_5_divergence")
    assert divergence.state == "off"
