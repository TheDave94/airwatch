"""Regression tests for the 2026-07 core review fixes.

Covers the entity-lifecycle and analytics core changes:

- Land Steiermark out-of-coverage is a successful-but-empty update (not an
  UpdateFailed), so an opted-in LS still loads the entry and its raw sensors are
  created (unavailable) rather than never existing.
- Entity creation is declaration-based, so a source is created even when its
  latest fetch carried no data.
- The consensus / divergence ``available`` guards don't raise when the analytics
  payload is ``None``.
- A failed, aged-out source is dropped from the cross-source consensus.
- ``async_remove_config_entry_device`` allows deleting a disabled source's
  stranded device.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.airwatch import async_remove_config_entry_device
from custom_components.airwatch.binary_sensor import DivergenceSensor
from custom_components.airwatch.const import (
    CONF_ENABLED,
    CONF_MAX_DISTANCE_KM,
    CONF_SELECTED_POLLUTANTS,
    CONF_SOURCES,
    CONF_STATION,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    SOURCE_LAND_STEIERMARK,
    SOURCE_OPEN_METEO,
)
from custom_components.airwatch.coordinator import (
    _is_source_stale,
    all_covered_pollutants,
    multi_source_pollutants,
)
from custom_components.airwatch.sensor import ConsensusSensor
from custom_components.airwatch.sources.open_meteo import BASE_URL as OM_URL

_POLLUTANTS = ["pm2_5", "pm10"]
_LS_DATASTREAMS = (
    "https://airquality-frost.k8s.ilt-dmz.iosb.fraunhofer.de/v1.1/Datastreams"
)


def _om_payload() -> dict:
    now = dt_util.now().replace(minute=0, second=0, microsecond=0)
    times = [
        (now - timedelta(days=1) + timedelta(hours=6 * i)).strftime("%Y-%m-%dT%H:00")
        for i in range(12)
    ]
    hourly = {"time": times}
    current = {"time": now.strftime("%Y-%m-%dT%H:00")}
    units = {}
    for p, val in (("pm2_5", 12.0), ("pm10", 20.0)):
        hourly[p] = [val for _ in times]
        current[p] = val
        units[p] = "µg/m³"
    return {
        "latitude": 48.2, "longitude": 16.4, "timezone": "Europe/Vienna",
        "elevation": 363.0, "hourly_units": units, "current": current,
        "hourly": hourly,
    }


def _entry_with_ls() -> MockConfigEntry:
    sources = {
        SOURCE_OPEN_METEO: {CONF_ENABLED: True},
        SOURCE_LAND_STEIERMARK: {
            CONF_ENABLED: True,
            CONF_STATION: "",
            CONF_MAX_DISTANCE_KM: 25.0,
        },
    }
    return MockConfigEntry(
        domain=DOMAIN, version=1, unique_id="48.2100_16.3700",
        title="AirWatch (48.210, 16.370)",
        data={CONF_LATITUDE: 48.21, CONF_LONGITUDE: 16.37},
        options={
            CONF_SELECTED_POLLUTANTS: _POLLUTANTS,
            CONF_UPDATE_INTERVAL: 60,
            CONF_SOURCES: sources,
        },
    )


async def test_land_steiermark_out_of_coverage_still_loads_and_creates_sensors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An opted-in LS with no in-range station loads the entry and creates its
    (unavailable) raw sensors instead of raising UpdateFailed and vanishing."""
    aioclient_mock.get(OM_URL, json=_om_payload())
    # Empty discovery => LandSteiermarkSource returns OUT_OF_COVERAGE, which the
    # coordinator now treats as a successful-but-empty update.
    aioclient_mock.get(_LS_DATASTREAMS, json={"value": []})

    entry = _entry_with_ls()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # The entry loaded despite LS having no data (it is not a transient failure).
    assert entry.state is ConfigEntryState.LOADED
    # Open-Meteo sensors work normally.
    assert float(hass.states.get("sensor.airwatch_open_meteo_pm2_5").state) == 12.0
    # The Land Steiermark raw sensor was CREATED (declaration-based) but is
    # unavailable — the opted-in user sees it reporting no data, not nothing.
    ls_pm = hass.states.get("sensor.airwatch_land_steiermark_pm2_5")
    assert ls_pm is not None
    assert ls_pm.state == "unavailable"


def test_covered_pollutant_helpers_are_declaration_based() -> None:
    """Coverage is a property of enabled sources, not the last fetch."""
    coords = {
        "open_meteo": SimpleNamespace(
            source=SimpleNamespace(pollutants=["pm2_5", "pm10", "ozone"])
        ),
        "sensor_community": SimpleNamespace(
            source=SimpleNamespace(pollutants=["pm2_5", "pm10"])
        ),
    }
    # ozone is single-source; pm2_5/pm10 are multi-source.
    assert all_covered_pollutants(coords) == ["ozone", "pm10", "pm2_5"]
    assert multi_source_pollutants(coords) == ["pm10", "pm2_5"]


def test_is_source_stale() -> None:
    """A failed source is dropped only once its cached data has aged out."""
    interval = timedelta(minutes=15)
    fresh = (dt_util.now() - timedelta(minutes=5)).isoformat()
    old = (dt_util.now() - timedelta(hours=3)).isoformat()

    # Successful refresh is never stale, regardless of timestamp.
    assert not _is_source_stale(
        SimpleNamespace(last_update_success=True, data=None, update_interval=interval)
    )
    # Failed but recent (within 3x interval) — tolerated, not stale.
    assert not _is_source_stale(
        SimpleNamespace(
            last_update_success=False,
            data=SimpleNamespace(generated_at=fresh),
            update_interval=interval,
        )
    )
    # Failed and aged out — stale.
    assert _is_source_stale(
        SimpleNamespace(
            last_update_success=False,
            data=SimpleNamespace(generated_at=old),
            update_interval=interval,
        )
    )
    # Failed with no usable timestamp — treated as stale.
    assert _is_source_stale(
        SimpleNamespace(
            last_update_success=False,
            data=SimpleNamespace(generated_at=None),
            update_interval=interval,
        )
    )


def test_consensus_and_divergence_available_do_not_raise_on_none_data() -> None:
    """available must not AttributeError when the analytics payload is None."""
    entry = SimpleNamespace(entry_id="abc123")
    coordinator = SimpleNamespace(last_update_success=False, data=None)

    consensus = ConsensusSensor(coordinator, entry, "pm2_5")
    divergence = DivergenceSensor(coordinator, entry, "pm2_5")

    # Both must return False (unavailable), not raise.
    assert consensus.available is False
    assert divergence.available is False


async def test_remove_config_entry_device_allows_disabled_source() -> None:
    """A stranded device for a disabled source is removable; active ones aren't."""
    entry = SimpleNamespace(
        entry_id="e1",
        runtime_data=SimpleNamespace(coordinators={SOURCE_OPEN_METEO: object()}),
    )
    active_device = SimpleNamespace(
        identifiers={(DOMAIN, f"e1_{SOURCE_OPEN_METEO}")}
    )
    analytics_device = SimpleNamespace(identifiers={(DOMAIN, "e1_analytics")})
    stranded_device = SimpleNamespace(
        identifiers={(DOMAIN, f"e1_{SOURCE_LAND_STEIERMARK}")}
    )

    assert await async_remove_config_entry_device(None, entry, active_device) is False
    assert await async_remove_config_entry_device(None, entry, analytics_device) is False
    assert await async_remove_config_entry_device(None, entry, stranded_device) is True


def _fresh_ts() -> str:
    return (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
