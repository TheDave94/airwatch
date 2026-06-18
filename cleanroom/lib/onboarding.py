"""HA onboarding walk — first-user creation + long-lived access token.

Replaces the manual browser step. Walks:

  POST /api/onboarding/users          (creates owner, returns auth_code)
  POST /auth/token                    (exchange auth_code for short-lived access_token)
  POST /api/onboarding/core_config    (sets country / TZ / coords / unit system)
  POST /api/onboarding/integration    (marks integration step done)
  POST /api/onboarding/analytics      (opts out of telemetry — optional)
  WS   auth/long_lived_access_token   (mints a long-lived token)

The long-lived-token endpoint is WebSocket-only in current HA — the historic
`POST /api/auth/long_lived_access_token` REST endpoint returns 404 in HA 2026.x.
Falls back to the short-lived access_token if the WS mint fails (with WARN).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from websockets.sync.client import connect as _ws_connect


@dataclass
class OnboardingResult:
    long_lived_token: str
    owner_username: str
    client_id: str


def _post_json(base_url: str, path: str, payload: dict, token: str | None = None,
               timeout: int = 30) -> tuple[int, dict | str | None]:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode(),
        method="POST",
        headers=h,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            txt = resp.read().decode()
            try:
                return resp.status, (json.loads(txt) if txt else None)
            except json.JSONDecodeError:
                return resp.status, txt
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(body) if body else None
        except json.JSONDecodeError:
            return e.code, body


def _post_form(base_url: str, path: str, payload: dict,
               timeout: int = 30) -> tuple[int, dict | str | None]:
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            txt = resp.read().decode()
            return resp.status, (json.loads(txt) if txt else None)
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(body) if body else None
        except json.JSONDecodeError:
            return e.code, body


def walk_onboarding(
    base_url: str,
    *,
    owner_name: str,
    owner_username: str,
    owner_password: str,
    language: str,
    country: str,
    location_name: str,
    latitude: float,
    longitude: float,
    elevation: int,
    time_zone: str,
    currency: str = "EUR",
    unit_system: str = "metric",
    client_id: str | None = None,
    long_lived_token_name: str = "cleanroom",
) -> OnboardingResult:
    """Walk the onboarding flow end-to-end. Raises on any step failure."""
    client_id = client_id or (base_url.rstrip("/") + "/")

    # 1. Create owner user
    st, body = _post_json(base_url, "/api/onboarding/users", {
        "client_id": client_id,
        "name": owner_name,
        "username": owner_username,
        "password": owner_password,
        "language": language,
    })
    if st != 200 or not isinstance(body, dict) or "auth_code" not in body:
        raise RuntimeError(f"/api/onboarding/users failed: HTTP {st}: {body!r}")
    auth_code = body["auth_code"]

    # 2. Exchange for access token
    st, body = _post_form(base_url, "/auth/token", {
        "client_id": client_id,
        "code": auth_code,
        "grant_type": "authorization_code",
    })
    if st != 200 or not isinstance(body, dict) or "access_token" not in body:
        raise RuntimeError(f"/auth/token exchange failed: HTTP {st}: {body!r}")
    access_token = body["access_token"]

    # 3. Set core config
    st, body = _post_json(base_url, "/api/onboarding/core_config", {
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
    }, token=access_token)
    if st not in (200, 204):
        raise RuntimeError(f"/api/onboarding/core_config failed: HTTP {st}: {body!r}")

    # 4. Mark integration step done (HA wants this even if no extra integrations
    #    were added during onboarding).
    st, body = _post_json(base_url, "/api/onboarding/integration", {
        "client_id": client_id,
        "redirect_uri": client_id,
    }, token=access_token)
    if st not in (200, 204):
        # Some HA versions return non-200 here harmlessly; don't fail hard.
        print(f"  ! /api/onboarding/integration returned HTTP {st} (continuing): {body!r}")

    # 5. Analytics opt-out (best-effort; older HA may not have this endpoint)
    st, body = _post_json(base_url, "/api/onboarding/analytics", {}, token=access_token)
    # 200/404 both fine.

    # 6. Mint long-lived token via WebSocket.
    #    The historic REST endpoint /api/auth/long_lived_access_token returns
    #    404 in HA 2026.x; the WS command is the supported path.
    long_lived_token = _mint_long_lived_ws(
        base_url, access_token, client_name=long_lived_token_name, lifespan_days=365,
    )
    if not long_lived_token:
        print("  WARN long-lived-token mint failed; falling back to short-lived "
              "access_token (lifetime ~30 min)")
        long_lived_token = access_token

    return OnboardingResult(
        long_lived_token=long_lived_token,
        owner_username=owner_username,
        client_id=client_id,
    )


def _mint_long_lived_ws(base_url: str, access_token: str, *,
                        client_name: str, lifespan_days: int) -> str | None:
    """Mint a long-lived access token via the WS auth/long_lived_access_token
    command. Returns the token string or None on any error."""
    scheme, host_port = base_url.rstrip("/").split("://", 1)
    ws_url = ("ws" if scheme == "http" else "wss") + "://" + host_port + "/api/websocket"
    try:
        with _ws_connect(ws_url, max_size=20 * 1024 * 1024, open_timeout=10) as ws:
            hello = json.loads(ws.recv())
            if hello.get("type") != "auth_required":
                return None
            ws.send(json.dumps({"type": "auth", "access_token": access_token}))
            auth = json.loads(ws.recv())
            if auth.get("type") != "auth_ok":
                return None
            ws.send(json.dumps({
                "id": 1,
                "type": "auth/long_lived_access_token",
                "client_name": client_name,
                "lifespan": lifespan_days,
            }))
            while True:
                r = json.loads(ws.recv())
                if r.get("id") == 1 and r.get("type") == "result":
                    if r.get("success") and isinstance(r.get("result"), str):
                        return r["result"]
                    return None
    except Exception as e:
        print(f"  WARN WS long-lived-token mint raised: {e}")
        return None
