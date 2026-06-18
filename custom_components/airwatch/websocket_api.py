"""WebSocket API for the AirWatch frontend card.

Single command for now: ``airwatch/config`` — returns the per-config-entry
pollutant selection plus the domain and the canonical pollutant display names
the bundled Lovelace card needs to render without YAML.

Registration is idempotent and one-shot per HA boot: the integration registers
once on first ``async_setup_entry`` call via :func:`async_register`. Ported
~as-is from PollenWatch ``websocket_api.py``.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_SELECTED_POLLUTANTS,
    DEFAULT_SELECTED_POLLUTANTS,
    DOMAIN,
    POLLUTANT_NAMES,
)

_REGISTERED_KEY = "airwatch_ws_registered"

_WS_TYPE_CONFIG = "airwatch/config"


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register WS commands once per HA boot. Idempotent.

    Called from ``async_setup_entry`` so the registration follows the first
    entry's load — the integration has no ``async_setup`` and the HACS pattern
    is to do one-shot wiring on the first per-entry call.
    """
    if hass.data.get(_REGISTERED_KEY):
        return
    hass.data[_REGISTERED_KEY] = True
    websocket_api.async_register_command(hass, _ws_get_config)


@websocket_api.websocket_command(
    {
        vol.Required("type"): _WS_TYPE_CONFIG,
        vol.Required("entry_id"): str,
    }
)
@callback
def _ws_get_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Return the card config for an AirWatch entry.

    Returns ``{domain, selected_pollutants, pollutant_names}``. An unknown
    ``entry_id`` (or one not owned by this domain) returns a clean
    ``not_found`` error frame, not an exception — the card surfaces this as a
    soft fallback (scan ``hass.states``) rather than a hard failure.
    """
    entry_id = msg["entry_id"]
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(
            msg["id"],
            "not_found",
            f"No AirWatch config entry with id {entry_id!r}",
        )
        return

    options = entry.options or {}
    selected_pollutants = list(
        options.get(CONF_SELECTED_POLLUTANTS) or DEFAULT_SELECTED_POLLUTANTS
    )

    connection.send_result(
        msg["id"],
        {
            "domain": DOMAIN,
            "selected_pollutants": selected_pollutants,
            "pollutant_names": dict(POLLUTANT_NAMES),
        },
    )


__all__ = ["async_register"]
