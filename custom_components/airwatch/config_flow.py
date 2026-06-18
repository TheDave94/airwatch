"""Config and options flow for AirWatch.

v1 "one-source vertical slice": a single user step that collects location,
pollutant selection, and the update interval for the Open-Meteo (CAMS) source,
with a coverage probe that refuses locations outside CAMS European coverage
(detected via the source's out-of-coverage status, which comes from
Open-Meteo's HTTP 400 error body — not from all-zero values). Location is
intentionally fixed after setup; pollutants and the update interval are
editable in the options flow.

The multi-source enablement UI (Sensor.Community, Land Steiermark) is out of
scope for v1: ``new_sources_config()`` seeds those sources disabled and the
flow leaves them out entirely.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_SELECTED_POLLUTANTS,
    CONF_SOURCES,
    CONF_UPDATE_INTERVAL,
    DEFAULT_SELECTED_POLLUTANTS,
    DEFAULT_UPDATE_INTERVAL_MIN,
    DOMAIN,
    MAX_UPDATE_INTERVAL_MIN,
    MIN_UPDATE_INTERVAL_MIN,
    new_sources_config,
)
from .coordinator import AirWatchConfigEntry, _entry_option
from .sources.base import POLLUTANTS, SourceError, SourceStatus
from .sources.open_meteo import OpenMeteoSource
from .sources.pollutant_registry import CANONICAL_POLLUTANTS

CONF_LOCATION = "location"


def _pollutant_selector() -> selector.SelectSelector:
    """Build the pollutant multi-select.

    Options are the canonical pollutant keys from ``POLLUTANTS`` (the seven
    Open-Meteo air-quality variables); labels come from the canonical registry
    so a renamed/added pollutant flows through automatically.
    """
    options = [
        selector.SelectOptionDict(
            value=key, label=CANONICAL_POLLUTANTS[key].name
        )
        for key in POLLUTANTS
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            multiple=True,
            mode=selector.SelectSelectorMode.LIST,
        )
    )


_INTERVAL_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=MIN_UPDATE_INTERVAL_MIN,
        max=MAX_UPDATE_INTERVAL_MIN,
        step=15,
        unit_of_measurement="min",
        mode=selector.NumberSelectorMode.BOX,
    )
)


async def _async_probe_coverage(
    hass, latitude: float, longitude: float, pollutants: list[str]
) -> str | None:
    """Return a config-flow error key if the location can't be used, else None.

    Mirrors PollenWatch's coverage probe: construct an OpenMeteoSource and fetch
    with HA's shared aiohttp session. A transport failure surfaces as
    ``cannot_connect``; an out-of-coverage status (Open-Meteo HTTP 400 body)
    surfaces as ``out_of_coverage``.
    """
    source = OpenMeteoSource(
        latitude, longitude, pollutants, past_days=0, forecast_days=1
    )
    try:
        result = await source.async_fetch(session=async_get_clientsession(hass))
    except SourceError:
        return "cannot_connect"
    if result.status is SourceStatus.OUT_OF_COVERAGE:
        return "out_of_coverage"
    return None


class AirWatchConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup of an AirWatch config entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single setup step: location + pollutants + interval.

        Probes Open-Meteo coverage after submission; on success creates the
        entry with location in ``data`` and the pollutant selection, update
        interval, and seeded per-source config in ``options``.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            location = user_input[CONF_LOCATION]
            latitude = location[CONF_LATITUDE]
            longitude = location[CONF_LONGITUDE]
            pollutants = list(user_input.get(CONF_SELECTED_POLLUTANTS, []))
            interval = int(user_input[CONF_UPDATE_INTERVAL])

            await self.async_set_unique_id(f"{latitude:.4f}_{longitude:.4f}")
            self._abort_if_unique_id_configured()

            if not pollutants:
                errors[CONF_SELECTED_POLLUTANTS] = "no_pollutants"
            else:
                # Probe with the user's selection — a connectivity + coverage
                # check (OM silent-drops unknown pollutants).
                error = await _async_probe_coverage(
                    self.hass, latitude, longitude, pollutants
                )
                if error == "out_of_coverage":
                    return self.async_abort(reason="out_of_coverage")
                if error:
                    errors["base"] = error
                else:
                    return self.async_create_entry(
                        title=f"AirWatch ({latitude:.3f}, {longitude:.3f})",
                        data={
                            CONF_LATITUDE: latitude,
                            CONF_LONGITUDE: longitude,
                        },
                        options={
                            CONF_SELECTED_POLLUTANTS: pollutants,
                            CONF_UPDATE_INTERVAL: interval,
                            CONF_SOURCES: new_sources_config(),
                        },
                    )

        suggested_location = {
            CONF_LATITUDE: self.hass.config.latitude,
            CONF_LONGITUDE: self.hass.config.longitude,
        }
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LOCATION, default=suggested_location
                ): selector.LocationSelector(
                    selector.LocationSelectorConfig(radius=False)
                ),
                vol.Required(
                    CONF_SELECTED_POLLUTANTS,
                    default=list(DEFAULT_SELECTED_POLLUTANTS),
                ): _pollutant_selector(),
                vol.Required(
                    CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL_MIN
                ): _INTERVAL_SELECTOR,
            }
        )
        # On an error re-render, re-seed the form with what the user submitted
        # (location/pollutants/interval) instead of resetting to defaults.
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: AirWatchConfigEntry,
    ) -> AirWatchOptionsFlow:
        return AirWatchOptionsFlow()


class AirWatchOptionsFlow(OptionsFlow):
    """Edit pollutants and the update interval after setup.

    Location is fixed (remove + re-add to change it). Multi-source enablement
    is out of scope for v1; the seeded ``CONF_SOURCES`` config is preserved
    untouched.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry

        if user_input is not None:
            pollutants = list(user_input.get(CONF_SELECTED_POLLUTANTS, []))
            if not pollutants:
                errors[CONF_SELECTED_POLLUTANTS] = "no_pollutants"
            else:
                # Preserve the seeded per-source config (v1 doesn't edit it).
                sources = _entry_option(
                    entry, CONF_SOURCES, new_sources_config()
                )
                return self.async_create_entry(
                    data={
                        CONF_SELECTED_POLLUTANTS: pollutants,
                        CONF_UPDATE_INTERVAL: int(
                            user_input[CONF_UPDATE_INTERVAL]
                        ),
                        CONF_SOURCES: sources,
                    }
                )

        current_pollutants = _entry_option(
            entry, CONF_SELECTED_POLLUTANTS, DEFAULT_SELECTED_POLLUTANTS
        )
        current_interval = _entry_option(
            entry, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MIN
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_POLLUTANTS, default=list(current_pollutants)
                ): _pollutant_selector(),
                vol.Required(
                    CONF_UPDATE_INTERVAL, default=current_interval
                ): _INTERVAL_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )
