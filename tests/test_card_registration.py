"""Card static-path registration — the previously-untested wiring path.

``__init__._async_register_card`` serves the bundled Lovelace card from a
registered static path and adds the cache-busted ``extra_js_url`` so the browser
loads it. This was the one untested path in the integration (the JS itself runs
in the browser, but the *registration* is plain Python). These tests exercise it
directly with a minimal fake hass so the assertions stay focused on the wiring,
not on a full HA bring-up.

They also pin two real invariants of the shipped artifact: the bundled
``airwatch-card.js`` exists on disk (otherwise registration silently no-ops), and
the served URL is cache-busted by the manifest version.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from custom_components import airwatch
from custom_components.airwatch import (
    _CARD_FILE,
    _CARD_LOADED_KEY,
    _CARD_URL_BASE,
    _async_register_card,
)

_FRONTEND_DIR = Path(airwatch.__file__).parent / "frontend"


class _FakeHass:
    """Just enough hass surface for ``_async_register_card``."""

    def __init__(self, http: object | None) -> None:
        self.data: dict = {}
        self.http = http

    async def async_add_executor_job(self, func, *args):  # noqa: ANN001
        return func(*args)


def test_bundled_card_file_is_present() -> None:
    """The real card bundle must exist or registration is a silent no-op."""
    card = _FRONTEND_DIR / _CARD_FILE
    assert card.is_file(), f"missing bundled card at {card}"
    # Sanity: it's the real card, not the old TODO stub.
    text = card.read_text(encoding="utf-8")
    assert "customElements.define('airwatch-card'" in text


async def test_register_card_serves_path_and_adds_js() -> None:
    """Registration serves the frontend dir and adds the cache-busted JS URL."""
    http = SimpleNamespace(async_register_static_paths=AsyncMock())
    hass = _FakeHass(http)

    with patch(
        "homeassistant.components.frontend.add_extra_js_url"
    ) as add_js:
        await _async_register_card(hass)

    # Static path registered for the bundled frontend directory.
    http.async_register_static_paths.assert_awaited_once()
    configs = http.async_register_static_paths.await_args.args[0]
    assert len(configs) == 1
    assert configs[0].url_path == _CARD_URL_BASE
    assert configs[0].path == str(_FRONTEND_DIR)

    # Extra JS URL points at the real card file, cache-busted by manifest version.
    add_js.assert_called_once()
    url = add_js.call_args.args[1]
    manifest = json.loads((_FRONTEND_DIR.parent / "manifest.json").read_text())
    assert url == f"{_CARD_URL_BASE}/{_CARD_FILE}?v={manifest['version']}"

    # Idempotency latch set.
    assert hass.data[_CARD_LOADED_KEY] is True


async def test_register_card_is_idempotent() -> None:
    """A second call (latch already set) does nothing."""
    http = SimpleNamespace(async_register_static_paths=AsyncMock())
    hass = _FakeHass(http)
    hass.data[_CARD_LOADED_KEY] = True

    with patch(
        "homeassistant.components.frontend.add_extra_js_url"
    ) as add_js:
        await _async_register_card(hass)

    http.async_register_static_paths.assert_not_awaited()
    add_js.assert_not_called()


async def test_register_card_noop_without_http() -> None:
    """Non-frontend HA contexts (no http) are a clean no-op, latch unset."""
    hass = _FakeHass(http=None)

    with patch(
        "homeassistant.components.frontend.add_extra_js_url"
    ) as add_js:
        await _async_register_card(hass)

    add_js.assert_not_called()
    assert _CARD_LOADED_KEY not in hass.data
