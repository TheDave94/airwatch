"""REST helpers for talking to a clean-room HA instance.

Thin wrapper around urllib so the cleanroom system has zero non-stdlib
dependencies for plain HTTP (websockets is the only third-party dep, used by
ha_ws.py).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


class HAClient:
    """Authenticated REST client for a single clean-room HA.

    Token-less mode is allowed (token=None) for the onboarding walk; once
    onboarding mints a token, construct a new HAClient with it for everything
    after.
    """

    def __init__(self, base_url: str, token: str | None = None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if extra:
            h.update(extra)
        return h

    def request(
        self,
        path: str,
        method: str = "GET",
        data: Any = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> tuple[int, Any]:
        url = self.base_url + path
        h = self._headers(headers)
        body: bytes | None = None
        if data is not None:
            body = json.dumps(data).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                txt = resp.read().decode()
                try:
                    return resp.status, (json.loads(txt) if txt else None)
                except json.JSONDecodeError:
                    return resp.status, txt
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if e.fp else ""
            try:
                return e.code, json.loads(err_body) if err_body else None
            except json.JSONDecodeError:
                return e.code, err_body

    # ---- common operations ----

    def wait_until_up(self, timeout: int = 90, poll_interval: float = 2.0) -> bool:
        """Poll GET /api/ until HA is serving HTTP. 200, 401, or 403 all count
        (before onboarding completes, /api/ returns 401 — that still means HA
        is up). Returns True on success, False on timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                # Use raw urllib here — HAClient.request raises some errors that
                # are normal during HA startup.
                req = urllib.request.Request(self.base_url + "/api/", method="GET")
                with urllib.request.urlopen(req, timeout=3) as r:
                    if r.status in (200, 401, 403):
                        return True
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    return True
            except Exception:
                pass
            time.sleep(poll_interval)
        return False

    def list_components(self) -> list[str]:
        """Return the loaded components list from /api/config."""
        st, cfg = self.request("/api/config")
        if st != 200 or not isinstance(cfg, dict):
            return []
        return list(cfg.get("components", []))

    def has_component(self, domain: str) -> bool:
        return domain in self.list_components()

    def wait_for_component(self, domain: str, timeout: int = 60, poll: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.has_component(domain):
                return True
            time.sleep(poll)
        return False

    def list_config_entries(self, domain: str | None = None) -> list[dict]:
        path = "/api/config/config_entries/entry"
        if domain:
            path += f"?domain={domain}"
        st, entries = self.request(path)
        return entries if isinstance(entries, list) else []

    def get_state(self, entity_id: str) -> dict | None:
        st, data = self.request(f"/api/states/{entity_id}")
        return data if st == 200 and isinstance(data, dict) else None

    def all_states(self) -> list[dict]:
        st, data = self.request("/api/states")
        return data if isinstance(data, list) else []

    def set_core_config(
        self,
        latitude: float,
        longitude: float,
        elevation: int,
        country: str,
        time_zone: str,
        location_name: str,
        currency: str = "EUR",
        language: str = "en",
        unit_system: str = "metric",
    ) -> tuple[int, Any]:
        return self.request(
            "/api/config/core/update",
            method="POST",
            data={
                "latitude": latitude,
                "longitude": longitude,
                "elevation": elevation,
                "unit_system": unit_system,
                "location_name": location_name,
                "time_zone": time_zone,
                "currency": currency,
                "country": country,
                "language": language,
                "radius": 100,
                "external_url": None,
                "internal_url": None,
            },
        )
