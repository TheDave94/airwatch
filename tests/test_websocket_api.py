"""Tests for the airwatch/config WebSocket API endpoint.

The card fetches the user's selected pollutants + the canonical pollutant
display names via this endpoint so it can render without YAML. Three things
matter: a configured entry mirrors options; an unknown / foreign entry_id
returns a clean ``not_found`` error frame (never a 500); and registration is
idempotent.

Strategy mirrors PollenWatch: the handler is a plain ``(hass, connection, msg)``
callback, so it is invoked directly with a stand-in ``ActiveConnection`` that
captures send_result / send_error. This is the faithful unit surface and avoids
spinning up the full aiohttp WS stack.
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airwatch.const import (
    CONF_SELECTED_POLLUTANTS,
    CONF_SOURCES,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    new_sources_config,
)
from custom_components.airwatch.websocket_api import _ws_get_config, async_register


class _CapturingConnection:
    """Minimal ActiveConnection stand-in: captures send_result / send_error.

    The handler only invokes ``send_result`` / ``send_error`` and reads no other
    attribute, so this stub is the entire contract under test.
    """

    def __init__(self) -> None:
        self.results: list[tuple[int, Any]] = []
        self.errors: list[tuple[int, str, str]] = []

    def send_result(self, msg_id: int, result: Any) -> None:
        self.results.append((msg_id, result))

    def send_error(self, msg_id: int, code: str, message: str) -> None:
        self.errors.append((msg_id, code, message))


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id="47.0700_15.4400",
        title="AirWatch (47.070, 15.440)",
        data={CONF_LATITUDE: 47.07, CONF_LONGITUDE: 15.44},
        options={
            CONF_SELECTED_POLLUTANTS: ["pm2_5", "carbon_monoxide"],
            CONF_UPDATE_INTERVAL: 60,
            CONF_SOURCES: new_sources_config(),
        },
    )


async def test_ws_config_returns_pollutants_and_names(hass: HomeAssistant) -> None:
    """A configured entry surfaces domain + selection + the names map."""
    entry = _entry()
    entry.add_to_hass(hass)

    connection = _CapturingConnection()
    _ws_get_config(hass, connection, {"id": 1, "entry_id": entry.entry_id})

    assert connection.errors == []
    assert len(connection.results) == 1
    msg_id, payload = connection.results[0]
    assert msg_id == 1
    assert payload["domain"] == DOMAIN
    assert payload["selected_pollutants"] == ["pm2_5", "carbon_monoxide"]
    names = payload["pollutant_names"]
    assert isinstance(names, dict)
    assert names["pm2_5"] == "PM2.5"


async def test_ws_config_unknown_entry_id_returns_clean_error(
    hass: HomeAssistant,
) -> None:
    """An entry_id the integration doesn't own → not_found error frame."""
    connection = _CapturingConnection()
    _ws_get_config(
        hass, connection, {"id": 42, "entry_id": "this-entry-does-not-exist"}
    )

    assert connection.results == []
    assert len(connection.errors) == 1
    msg_id, code, _message = connection.errors[0]
    assert msg_id == 42
    assert code == "not_found"


async def test_ws_config_rejects_foreign_domain_entry(hass: HomeAssistant) -> None:
    """A ConfigEntry from another integration must not leak through this endpoint."""
    foreign = MockConfigEntry(domain="other_integration", data={})
    foreign.add_to_hass(hass)

    connection = _CapturingConnection()
    _ws_get_config(hass, connection, {"id": 5, "entry_id": foreign.entry_id})

    assert connection.results == []
    assert len(connection.errors) == 1
    assert connection.errors[0][1] == "not_found"


async def test_ws_config_falls_back_to_default_selection(hass: HomeAssistant) -> None:
    """An entry with no selection option falls back to the default pollutants."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id="48.0000_16.0000",
        data={CONF_LATITUDE: 48.0, CONF_LONGITUDE: 16.0},
        options={},
    )
    entry.add_to_hass(hass)

    connection = _CapturingConnection()
    _ws_get_config(hass, connection, {"id": 8, "entry_id": entry.entry_id})

    assert connection.errors == []
    selected = connection.results[0][1]["selected_pollutants"]
    # Defaults to all canonical pollutants (DEFAULT_SELECTED_POLLUTANTS).
    assert "pm2_5" in selected
    assert "european_aqi" in selected


async def test_ws_register_is_idempotent(hass: HomeAssistant) -> None:
    """async_register is one-shot per HA boot; a second call must not raise."""
    async_register(hass)
    async_register(hass)  # must not raise / re-register
