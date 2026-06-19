"""Config and options flow for AirWatch.

v1 "one-source vertical slice": a single user step that collects location,
pollutant selection, and the update interval for the Open-Meteo (CAMS) source,
with a coverage probe that refuses locations outside CAMS European coverage
(detected via the source's out-of-coverage status, which comes from
Open-Meteo's HTTP 400 error body — not from all-zero values). Location is
intentionally fixed after setup; pollutants and the update interval are
editable in the options flow.

The optional secondary sources (Sensor.Community, Land Steiermark) are exposed
as opt-in toggles in both the initial step and the options flow; both default to
disabled. Land Steiermark is a lagged drift-anchor feed (see its source module),
so it is opt-in and surfaces its staleness rather than asserting live values.
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
    CONF_ENABLED,
    CONF_MAX_DISTANCE_KM,
    CONF_SELECTED_POLLUTANTS,
    CONF_SOURCES,
    CONF_STATION,
    CONF_STATIONS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_MAX_DISTANCE_KM,
    DEFAULT_SELECTED_POLLUTANTS,
    DEFAULT_UPDATE_INTERVAL_MIN,
    DOMAIN,
    LAND_STEIERMARK_MAX_DISTANCE_KM,
    MAX_UPDATE_INTERVAL_MIN,
    MIN_UPDATE_INTERVAL_MIN,
    SOURCE_LAND_STEIERMARK,
    SOURCE_SENSOR_COMMUNITY,
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

# --- optional Sensor.Community secondary source ---------------------------
# Flow-local field keys (mapped onto the CONF_SOURCES[sensor_community] config).
CONF_ENABLE_SC = "enable_sensor_community"
CONF_SC_DISTANCE = "sensor_community_distance_km"
CONF_SC_STATIONS = "sensor_community_stations"

_SC_DISTANCE_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=1, max=50, step=1, unit_of_measurement="km",
        mode=selector.NumberSelectorMode.BOX,
    )
)


def _parse_station_ids(raw: str) -> list[int]:
    """Parse a comma-separated station-id string into a list of ints.

    Non-numeric tokens are dropped silently — an empty result means
    auto-discover the nearest sensors by distance.
    """
    ids: list[int] = []
    for token in (raw or "").replace(" ", "").split(","):
        if not token:
            continue
        try:
            ids.append(int(token))
        except ValueError:
            continue
    return ids


def _sc_schema_fields(
    *, enabled: bool, distance: float, stations: list[int] | None
) -> dict:
    """Schema fields for the optional Sensor.Community source (config + options)."""
    return {
        vol.Optional(CONF_ENABLE_SC, default=enabled): selector.BooleanSelector(),
        vol.Optional(
            CONF_SC_DISTANCE, default=distance
        ): _SC_DISTANCE_SELECTOR,
        vol.Optional(
            CONF_SC_STATIONS,
            default=",".join(str(s) for s in (stations or [])),
        ): selector.TextSelector(),
    }


def _apply_sc_input(sources: dict, user_input: dict) -> dict:
    """Overlay the submitted Sensor.Community fields onto a sources config.

    Returns the same dict for convenience. When the user leaves everything at
    its defaults this reproduces ``new_sources_config()``'s sensor_community
    entry exactly (enabled=False, default distance, no explicit stations).
    """
    sc = sources.setdefault(SOURCE_SENSOR_COMMUNITY, {})
    sc[CONF_ENABLED] = bool(user_input.get(CONF_ENABLE_SC, False))
    sc[CONF_MAX_DISTANCE_KM] = float(
        user_input.get(CONF_SC_DISTANCE, DEFAULT_MAX_DISTANCE_KM)
    )
    sc[CONF_STATIONS] = _parse_station_ids(user_input.get(CONF_SC_STATIONS, ""))
    return sources


# --- optional Land Steiermark secondary source (DRIFT ANCHOR) -------------
# Disabled by default (docs/dev/OPEN_QUESTIONS.md Q6): the official feed is a lagged,
# best-effort SensorThings harvest, surfaced as a slow drift anchor.
CONF_ENABLE_LS = "enable_land_steiermark"
CONF_LS_STATION = "land_steiermark_station"
CONF_LS_DISTANCE = "land_steiermark_distance_km"

_LS_DISTANCE_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=1, max=100, step=1, unit_of_measurement="km",
        mode=selector.NumberSelectorMode.BOX,
    )
)


def _ls_schema_fields(
    *, enabled: bool, station: str, distance: float
) -> dict:
    """Schema fields for the optional Land Steiermark source (config + options)."""
    return {
        vol.Optional(CONF_ENABLE_LS, default=enabled): selector.BooleanSelector(),
        vol.Optional(
            CONF_LS_DISTANCE, default=distance
        ): _LS_DISTANCE_SELECTOR,
        vol.Optional(
            CONF_LS_STATION, default=station or ""
        ): selector.TextSelector(),
    }


def _apply_ls_input(sources: dict, user_input: dict) -> dict:
    """Overlay the submitted Land Steiermark fields onto a sources config.

    Leaving everything at its defaults reproduces ``new_sources_config()``'s
    land_steiermark entry (disabled, default radius, no explicit station).
    """
    ls = sources.setdefault(SOURCE_LAND_STEIERMARK, {})
    ls[CONF_ENABLED] = bool(user_input.get(CONF_ENABLE_LS, False))
    ls[CONF_STATION] = str(user_input.get(CONF_LS_STATION, "") or "").strip()
    ls[CONF_MAX_DISTANCE_KM] = float(
        user_input.get(CONF_LS_DISTANCE, LAND_STEIERMARK_MAX_DISTANCE_KM)
    )
    return sources


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
                            CONF_SOURCES: _apply_ls_input(
                                _apply_sc_input(new_sources_config(), user_input),
                                user_input,
                            ),
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
                **_sc_schema_fields(
                    enabled=False, distance=DEFAULT_MAX_DISTANCE_KM, stations=[]
                ),
                **_ls_schema_fields(
                    enabled=False,
                    station="",
                    distance=LAND_STEIERMARK_MAX_DISTANCE_KM,
                ),
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

    Location is fixed (remove + re-add to change it). The optional secondary
    sources (Sensor.Community, Land Steiermark) are editable here; any source
    keys the UI doesn't expose are preserved untouched.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry

        # Copy current per-source config so we overlay (not mutate) it, and
        # preserve sources the v1 UI doesn't expose (e.g. Land Steiermark).
        current_sources = {
            key: dict(value)
            for key, value in _entry_option(
                entry, CONF_SOURCES, new_sources_config()
            ).items()
        }

        if user_input is not None:
            pollutants = list(user_input.get(CONF_SELECTED_POLLUTANTS, []))
            if not pollutants:
                errors[CONF_SELECTED_POLLUTANTS] = "no_pollutants"
            else:
                return self.async_create_entry(
                    data={
                        CONF_SELECTED_POLLUTANTS: pollutants,
                        CONF_UPDATE_INTERVAL: int(
                            user_input[CONF_UPDATE_INTERVAL]
                        ),
                        CONF_SOURCES: _apply_ls_input(
                            _apply_sc_input(current_sources, user_input),
                            user_input,
                        ),
                    }
                )

        current_pollutants = _entry_option(
            entry, CONF_SELECTED_POLLUTANTS, DEFAULT_SELECTED_POLLUTANTS
        )
        current_interval = _entry_option(
            entry, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MIN
        )
        sc_cfg = current_sources.get(SOURCE_SENSOR_COMMUNITY, {})
        ls_cfg = current_sources.get(SOURCE_LAND_STEIERMARK, {})
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_POLLUTANTS, default=list(current_pollutants)
                ): _pollutant_selector(),
                vol.Required(
                    CONF_UPDATE_INTERVAL, default=current_interval
                ): _INTERVAL_SELECTOR,
                **_sc_schema_fields(
                    enabled=bool(sc_cfg.get(CONF_ENABLED, False)),
                    distance=float(
                        sc_cfg.get(CONF_MAX_DISTANCE_KM, DEFAULT_MAX_DISTANCE_KM)
                    ),
                    stations=sc_cfg.get(CONF_STATIONS, []),
                ),
                **_ls_schema_fields(
                    enabled=bool(ls_cfg.get(CONF_ENABLED, False)),
                    station=str(ls_cfg.get(CONF_STATION, "") or ""),
                    distance=float(
                        ls_cfg.get(
                            CONF_MAX_DISTANCE_KM, LAND_STEIERMARK_MAX_DISTANCE_KM
                        )
                    ),
                ),
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )
