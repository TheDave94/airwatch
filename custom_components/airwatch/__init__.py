"""The AirWatch integration.

This package entry point is deliberately free of top-level ``homeassistant``
imports: importing the package (and therefore the source layer under
``sources/``) must not require Home Assistant, so the data layer stays testable
in isolation. The Home Assistant API is imported inside the entry functions,
which only run when HA loads the integration.

AirWatch starts at config-entry version 1, so there is no migration chain (the
PollenWatch v1→v2→v3 lossless-migration infra is intentionally not ported yet —
it returns when AirWatch first needs a schema change).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .const import DOMAIN, PLATFORMS

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceEntry

    from .coordinator import AirWatchConfigEntry

_LOGGER = logging.getLogger(__name__)

# Auto-register the bundled Lovelace card as a frontend resource (once per HA
# boot). The card lives at custom_components/airwatch/frontend/ and is served
# via a registered static path; cache-busted by manifest version. HACS uses the
# same pattern.
_CARD_URL_BASE = "/airwatch_card_static"
_CARD_FILE = "airwatch-card.js"
_CARD_LOADED_KEY = "airwatch_card_registered"

__all__ = [
    "DOMAIN",
    "async_remove_config_entry_device",
    "async_setup_entry",
    "async_unload_entry",
]


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve + register the bundled Lovelace card. Idempotent per HA boot."""
    if hass.data.get(_CARD_LOADED_KEY):
        return
    # HTTP isn't available in some non-frontend HA contexts (e.g. unit-test
    # harnesses that don't load the http component) — no-op there.
    if getattr(hass, "http", None) is None:
        return

    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    frontend_dir = Path(__file__).parent / "frontend"
    if not (frontend_dir / _CARD_FILE).is_file():
        _LOGGER.warning(
            "AirWatch card bundle not found at %s; card will not be served",
            frontend_dir / _CARD_FILE,
        )
        return

    # Cache-bust via manifest version so a HACS update reloads the JS in the
    # browser. Read in an executor — sync I/O on the event loop trips HA's
    # blocking-call detector. Catch ValueError too: a partially-written manifest
    # (e.g. an interrupted HACS update) raises JSONDecodeError, which must not
    # take down the whole config-entry setup over a cosmetic cache-buster.
    def _read_version() -> str:
        try:
            data = json.loads((Path(__file__).parent / "manifest.json").read_text())
            return data.get("version", "0")
        except (OSError, ValueError):
            return "0"

    version = await hass.async_add_executor_job(_read_version)

    # Latch AFTER a fully-successful registration, not before: an exception in
    # the register calls must not both fail the entry and leave the latch set
    # (which would silently skip the card on every later reload this boot).
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(_CARD_URL_BASE, str(frontend_dir), False)]
        )
        add_extra_js_url(hass, f"{_CARD_URL_BASE}/{_CARD_FILE}?v={version}")
    except Exception:  # noqa: BLE001 - card is cosmetic; never fail the entry over it
        _LOGGER.exception(
            "AirWatch Lovelace card registration failed; card will not be served"
        )
        return

    hass.data[_CARD_LOADED_KEY] = True
    _LOGGER.info("AirWatch Lovelace card registered (v%s)", version)


async def async_setup_entry(
    hass: HomeAssistant, entry: AirWatchConfigEntry
) -> bool:
    """Set up AirWatch from a config entry."""
    from homeassistant.const import Platform

    from .const import SOURCE_OPEN_METEO
    from .coordinator import (
        AirWatchAnalyticsCoordinator,
        AirWatchData,
        build_coordinators,
    )

    # One install delivers the integration AND the Lovelace card — auto-register
    # the card on first config-entry load (no-op on subsequent entries).
    await _async_register_card(hass)

    # Register the frontend-facing WS API once per HA boot. Idempotent.
    from .websocket_api import async_register as _async_register_ws

    _async_register_ws(hass)

    coordinators = build_coordinators(hass, entry)
    # Open-Meteo is the primary, keyless source: it must be ready or the entry
    # retries. Optional sources refresh non-blockingly so a failure there leaves
    # their sensors unavailable without taking the entry down.
    await coordinators[SOURCE_OPEN_METEO].async_config_entry_first_refresh()
    for source_key, coordinator in coordinators.items():
        if source_key != SOURCE_OPEN_METEO:
            await coordinator.async_refresh()

    # Analytics (derived) coordinator reads the source coordinators above.
    analytics = AirWatchAnalyticsCoordinator(hass, entry, coordinators)
    await analytics.async_refresh()

    # Recompute analytics whenever a source coordinator publishes new data,
    # rather than only on the analytics coordinator's own hourly clock — without
    # this the consensus / divergence lag their inputs by up to an hour (a source
    # polling every 15 min would disagree with its own raw sensor on the same
    # dashboard). async_request_refresh is debounced, so bursts coalesce.
    from homeassistant.core import callback

    @callback
    def _schedule_analytics_refresh() -> None:
        entry.async_create_task(hass, analytics.async_request_refresh())

    for coordinator in coordinators.values():
        entry.async_on_unload(
            coordinator.async_add_listener(_schedule_analytics_refresh)
        )

    entry.runtime_data = AirWatchData(
        coordinators=coordinators, analytics=analytics
    )

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform(p) for p in PLATFORMS]
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: AirWatchConfigEntry
) -> bool:
    """Unload a config entry."""
    from homeassistant.const import Platform

    return await hass.config_entries.async_unload_platforms(
        entry, [Platform(p) for p in PLATFORMS]
    )


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: AirWatchConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Allow deleting a device only when it no longer maps to an active source.

    Disabling a source in the options flow prunes its entities but leaves its
    per-source device stranded (zero entities) with no Delete button. Return
    True (allow removal) for any AirWatch device whose identifier does not
    belong to a currently-enabled source or the analytics device.
    """
    runtime = getattr(config_entry, "runtime_data", None)
    active_ids: set[tuple[str, str]] = {
        (DOMAIN, f"{config_entry.entry_id}_analytics")
    }
    if runtime is not None:
        active_ids.update(
            (DOMAIN, f"{config_entry.entry_id}_{source_key}")
            for source_key in runtime.coordinators
        )
    return not (device_entry.identifiers & active_ids)


async def _async_reload_entry(
    hass: HomeAssistant, entry: AirWatchConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
