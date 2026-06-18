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
    hass.data[_CARD_LOADED_KEY] = True

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
    # blocking-call detector.
    def _read_version() -> str:
        try:
            data = json.loads((Path(__file__).parent / "manifest.json").read_text())
            return data.get("version", "0")
        except OSError:
            return "0"

    version = await hass.async_add_executor_job(_read_version)

    await hass.http.async_register_static_paths(
        [StaticPathConfig(_CARD_URL_BASE, str(frontend_dir), False)]
    )
    add_extra_js_url(hass, f"{_CARD_URL_BASE}/{_CARD_FILE}?v={version}")
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


async def _async_reload_entry(
    hass: HomeAssistant, entry: AirWatchConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
