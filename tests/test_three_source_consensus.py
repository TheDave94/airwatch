"""Three-source integration: Open-Meteo + Sensor.Community + Land Steiermark.

Proves the drift-anchor third source wires all the way through the coordinator's
async path and shows up in cross-source consensus alongside the two live sources
(source_count reaches 3, max_possible 3). Exercises LandSteiermarkSource's real
aiohttp transport (the SensorThings discovery query is mocked). A fresh LS
reading is synthesised relative to "now" so it passes the drift-anchor staleness
window.
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
    CONF_STATION,
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
_LS_DATASTREAMS = (
    "https://airquality-frost.k8s.ilt-dmz.iosb.fraunhofer.de/v1.1/Datastreams"
)


def _om_payload() -> dict:
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
    ts = (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    return [
        {
            "timestamp": ts,
            "location": {"latitude": "47.07", "longitude": "15.44"},
            "sensor": {"id": _SC_STATION, "sensor_type": {"name": "SDS011"}},
            "sensordatavalues": [
                {"value_type": "P1", "value": "22.0"},
                {"value_type": "P2", "value": "13.0"},
            ],
        }
    ]


def _ls_payload() -> dict:
    """A fresh Land Steiermark discovery response (one Graz station, pm2_5)."""
    end = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0)
    start = end - timedelta(hours=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    phenomenon = f"{start.strftime(fmt)}/{end.strftime(fmt)}"
    station = {
        "name": "Graz Don Bosco",
        "properties": {"localId": "STA.06.164", "countryCode": "AT"},
        "Locations": [
            {"location": {"type": "Point", "coordinates": [15.4166, 47.0556]}}
        ],
    }
    return {
        "value": [
            {
                "Thing": station,
                "ObservedProperty": {"name": "PM2.5"},
                "Observations": [{"phenomenonTime": phenomenon, "result": 14.0}],
            },
            {
                "Thing": station,
                "ObservedProperty": {"name": "PM10"},
                "Observations": [{"phenomenonTime": phenomenon, "result": 21.0}],
            },
        ]
    }


def _entry() -> MockConfigEntry:
    sources = {
        SOURCE_OPEN_METEO: {CONF_ENABLED: True},
        SOURCE_SENSOR_COMMUNITY: {
            CONF_ENABLED: True,
            CONF_MAX_DISTANCE_KM: 10.0,
            CONF_STATIONS: [_SC_STATION],
        },
        SOURCE_LAND_STEIERMARK: {
            CONF_ENABLED: True,
            CONF_STATION: "",
            CONF_MAX_DISTANCE_KM: 25.0,
        },
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


async def test_three_sources_drive_consensus(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(OM_URL, json=_om_payload())
    aioclient_mock.get(_SC_URL, json=_sc_payload())
    aioclient_mock.get(_LS_DATASTREAMS, json=_ls_payload())

    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    # The drift-anchor source produced a raw pm2_5 sensor like the others.
    ls_pm = hass.states.get("sensor.airwatch_land_steiermark_pm2_5")
    assert ls_pm is not None and float(ls_pm.state) == 14.0
    # Its native value surfaces the station + age (drift-anchor provenance).
    assert "STA.06.164" in ls_pm.attributes.get("native_value", "")
    assert "old" in ls_pm.attributes.get("native_value", "")

    # Consensus now spans THREE sources for pm2_5.
    consensus = hass.states.get("sensor.airwatch_analytics_pm2_5_consensus")
    assert consensus is not None
    assert consensus.attributes["source_count"] == 3
    assert consensus.attributes["max_possible_sources"] == 3
    assert set(consensus.attributes["source_levels"]) == {
        SOURCE_OPEN_METEO,
        SOURCE_SENSOR_COMMUNITY,
        SOURCE_LAND_STEIERMARK,
    }
