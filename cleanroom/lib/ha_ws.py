"""WebSocket client for clean-room HA.

The institutional knowledge from the manual run lives here:

* `max_size=20 * 1024 * 1024` on the connect is REQUIRED. The default 1 MiB cap
  causes HACS responses (which include the full repository list) to abort the
  connection mid-message. The 20 MiB ceiling was empirically validated during
  the PollenWatch v1.3.0→HEAD manual cleanroom run (the harness AirWatch forks).

* Message contract: each outbound message gets a sequential `id` starting at 1
  per connection. Inbound messages arrive interleaved; the reader loops until
  it sees one with `type == "result"` and the matching `id`, then returns it.
  Don't try to fan out — open a fresh connection per logical call batch.
"""
from __future__ import annotations

import asyncio
import json

import websockets

_MAX_SIZE = 20 * 1024 * 1024  # see module docstring


class HAWebSocket:
    """Async WS client. Use one instance per logical batch of calls."""

    def __init__(self, base_url: str, token: str):
        # base_url is the HTTP form ("http://127.0.0.1:8200"); we derive the
        # WS URL ("ws://127.0.0.1:8200/api/websocket") here.
        scheme_split = base_url.split("://", 1)
        scheme = "ws" if scheme_split[0] == "http" else "wss"
        host_port = scheme_split[1].rstrip("/")
        self.ws_url = f"{scheme}://{host_port}/api/websocket"
        self.token = token

    async def call(self, messages: list[dict]) -> list[dict]:
        """Send a list of typed messages on a fresh connection. Returns the
        list of result dicts in send order. Each result dict is the raw HA WS
        response (`{"id", "type": "result", "success": bool, "result"|"error"}`)."""
        async with websockets.connect(self.ws_url, max_size=_MAX_SIZE) as ws:
            hello = json.loads(await ws.recv())
            assert hello["type"] == "auth_required", f"unexpected hello: {hello}"
            await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            auth = json.loads(await ws.recv())
            assert auth["type"] == "auth_ok", f"auth failed: {auth}"

            results: list[dict] = []
            for i, msg in enumerate(messages, start=1):
                msg_with_id = {**msg, "id": i}
                await ws.send(json.dumps(msg_with_id))
                while True:
                    raw = await ws.recv()
                    r = json.loads(raw)
                    if r.get("id") == i and r.get("type") == "result":
                        results.append(r)
                        break
            return results

    # ---- common WS calls ----

    async def entity_registry_list(self) -> list[dict]:
        r = await self.call([{"type": "config/entity_registry/list"}])
        return r[0]["result"] if r[0]["success"] else []

    async def device_registry_list(self) -> list[dict]:
        r = await self.call([{"type": "config/device_registry/list"}])
        return r[0]["result"] if r[0]["success"] else []

    async def config_entry_get(self, entry_id: str) -> dict | None:
        r = await self.call([{"type": "config_entries/get", "entry_id": entry_id}])
        if not r[0]["success"]:
            return None
        result = r[0]["result"]
        # WS returns a list when querying by entry_id; some HA versions return a
        # single dict. Normalize.
        if isinstance(result, list):
            return result[0] if result else None
        return result

    async def config_entries_by_domain(self, domain: str) -> list[dict]:
        r = await self.call([{"type": "config_entries/get", "domain": domain}])
        return r[0]["result"] if r[0]["success"] else []


def sync_call(base_url: str, token: str, messages: list[dict]) -> list[dict]:
    """Convenience: open a fresh event loop, run a single call(), return results.
    Use from non-async callers; not for tight loops."""
    ws = HAWebSocket(base_url, token)
    return asyncio.run(ws.call(messages))
