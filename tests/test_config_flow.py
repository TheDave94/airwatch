"""Tests for the AirWatch config and options flows.

The flow's coverage probe builds an :class:`OpenMeteoSource` and fetches it over
HA's shared aiohttp session, so the Open-Meteo HTTP endpoint is mocked
host-agnostic of the query string via the ``aioclient_mock`` fixture. A 200 with
a usable payload → success; a 400 ``{"error": true, "reason": "No data ..."}``
→ out-of-coverage; a raised ``aiohttp.ClientError`` → cannot_connect.
"""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.airwatch.config_flow import CONF_LOCATION
from custom_components.airwatch.const import (
    CONF_SELECTED_POLLUTANTS,
    CONF_SOURCES,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    new_sources_config,
)
from custom_components.airwatch.sources.open_meteo import BASE_URL

_LOCATION = {CONF_LATITUDE: 47.07, CONF_LONGITUDE: 15.44}


def _ok_payload() -> dict:
    """A minimal but well-formed Open-Meteo air-quality OK response.

    The coverage probe only needs an OK (status=OK, has ``hourly``) result; a
    couple of pollutants and a short time axis are enough.
    """
    return {
        "latitude": 47.1,
        "longitude": 15.4,
        "timezone": "Europe/Vienna",
        "elevation": 363.0,
        "hourly_units": {"pm2_5": "µg/m³", "pm10": "µg/m³"},
        "current": {"time": "2026-05-29T12:00", "pm2_5": 8.0, "pm10": 14.0},
        "hourly": {
            "time": ["2026-05-29T11:00", "2026-05-29T12:00"],
            "pm2_5": [7.0, 8.0],
            "pm10": [12.0, 14.0],
        },
    }


def _mock_ok(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(BASE_URL, json=_ok_payload())


def _mock_out_of_coverage(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        BASE_URL,
        status=400,
        json={"error": True, "reason": "No data is available for this location"},
    )


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_flow_creates_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Happy path: covered location + pollutants + interval → CREATE_ENTRY."""
    _mock_ok(aioclient_mock)

    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    # Mock the entry setup so the flow's CREATE_ENTRY doesn't spin up the real
    # integration (and its aiohttp resolver thread); the probe still runs over
    # the mocked HTTP endpoint above.
    with patch(
        "custom_components.airwatch.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_LOCATION: _LOCATION,
                CONF_SELECTED_POLLUTANTS: ["pm2_5", "pm10"],
                CONF_UPDATE_INTERVAL: 60,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_LATITUDE: 47.07, CONF_LONGITUDE: 15.44}
    assert result["options"][CONF_SELECTED_POLLUTANTS] == ["pm2_5", "pm10"]
    assert result["options"][CONF_UPDATE_INTERVAL] == 60
    assert result["options"][CONF_SOURCES] == new_sources_config()
    assert result["result"].unique_id == "47.0700_15.4400"


async def test_user_flow_out_of_coverage_aborts(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 400 out-of-coverage response aborts the flow."""
    _mock_out_of_coverage(aioclient_mock)

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_LOCATION: {CONF_LATITUDE: 40.71, CONF_LONGITUDE: -74.0},
            CONF_SELECTED_POLLUTANTS: ["pm2_5"],
            CONF_UPDATE_INTERVAL: 60,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "out_of_coverage"


async def test_user_flow_cannot_connect_shows_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A transport failure re-shows the form with a cannot_connect base error."""
    aioclient_mock.get(BASE_URL, exc=aiohttp.ClientError())

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_LOCATION: _LOCATION,
            CONF_SELECTED_POLLUTANTS: ["pm2_5"],
            CONF_UPDATE_INTERVAL: 60,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_requires_a_pollutant(hass: HomeAssistant) -> None:
    """An empty pollutant selection re-shows the form with no_pollutants.

    No HTTP mock: the empty-selection check short-circuits before the probe.
    """
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_LOCATION: _LOCATION,
            CONF_SELECTED_POLLUTANTS: [],
            CONF_UPDATE_INTERVAL: 60,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SELECTED_POLLUTANTS: "no_pollutants"}


async def test_duplicate_location_aborts(hass: HomeAssistant) -> None:
    """A second entry at the same rounded location aborts already_configured."""
    MockConfigEntry(domain=DOMAIN, unique_id="47.0700_15.4400").add_to_hass(hass)

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_LOCATION: _LOCATION,
            CONF_SELECTED_POLLUTANTS: ["pm2_5"],
            CONF_UPDATE_INTERVAL: 60,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_updates_pollutants_and_interval(
    hass: HomeAssistant,
) -> None:
    """The options flow rewrites the selection + interval and preserves sources."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="47.0700_15.4400",
        data={CONF_LATITUDE: 47.07, CONF_LONGITUDE: 15.44},
        options={
            CONF_SELECTED_POLLUTANTS: ["pm2_5", "pm10"],
            CONF_UPDATE_INTERVAL: 60,
            CONF_SOURCES: new_sources_config(),
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SELECTED_POLLUTANTS: ["pm2_5"], CONF_UPDATE_INTERVAL: 120},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SELECTED_POLLUTANTS] == ["pm2_5"]
    assert entry.options[CONF_UPDATE_INTERVAL] == 120
    # v1 does not edit per-source config — it must survive the options write.
    assert entry.options[CONF_SOURCES] == new_sources_config()


async def test_options_flow_requires_a_pollutant(hass: HomeAssistant) -> None:
    """An empty selection in the options flow re-shows the form with the error."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="47.0700_15.4400",
        data={CONF_LATITUDE: 47.07, CONF_LONGITUDE: 15.44},
        options={
            CONF_SELECTED_POLLUTANTS: ["pm2_5"],
            CONF_UPDATE_INTERVAL: 60,
            CONF_SOURCES: new_sources_config(),
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SELECTED_POLLUTANTS: [], CONF_UPDATE_INTERVAL: 60},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SELECTED_POLLUTANTS: "no_pollutants"}
