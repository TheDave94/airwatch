"""HACS WebSocket commands — institutional knowledge from the PollenWatch
v1.3.0→HEAD manual cleanroom run (the harness AirWatch forks).

If you change anything in this file, verify against a known-good cleanroom run
first — these command names + shapes are NOT well-documented upstream and were
discovered empirically.

Command-name surprises (do not "fix" without verifying):

* `hacs/repositories/add` — NOT `hacs/install` or `hacs/add`.
  Payload: `{repository: "<owner>/<repo>", category: "integration"}`.
  After add, sleep ~8s then re-list to find the assigned numeric `id`.

* `hacs/repository/download` — NOT `hacs/install` or `hacs/repository/install`.
  Payload: `{repository: "<numeric-id>", version: "<git-tag>"}`.
  Note: the field is `repository` (the ID), not `repository_id`. The `version`
  field takes the literal git tag string (e.g. `v1.0.0`).

* `hacs/repositories/list` — returns `{success: bool, result: [<repo>, ...]}`.
  Each repo has `id`, `full_name`, `installed`, `installed_version`,
  `available_version`, `category`, `custom`, `downloaded`.

* `hacs/repository {repository_id, action: "show"}` — per-repo detail. Uses
  `repository_id` (different field name from /download — yes, really).

The WS connection MUST use `max_size=20 MiB` (see ha_ws.py) — HACS responses
exceed the 1 MiB default.

Restart-after-download requirement: `hacs/repository/download` writes files to
`<config>/custom_components/<repo>/` but does NOT load the integration. The
container must be restarted (or the integration manually loaded) for HA to
pick it up.
"""
from __future__ import annotations

import asyncio
import time

from .ha_ws import HAWebSocket


async def list_repositories(ws: HAWebSocket) -> list[dict]:
    r = await ws.call([{"type": "hacs/repositories/list"}])
    if not r[0]["success"]:
        raise RuntimeError(f"hacs/repositories/list failed: {r[0]}")
    return r[0]["result"]


async def find_repository(ws: HAWebSocket, full_name: str) -> dict | None:
    """Find a repo by `full_name` (e.g. 'TheDave94/airwatch'). Returns the
    repo dict (with .id, .installed_version, etc.) or None."""
    repos = await list_repositories(ws)
    for repo in repos:
        if repo.get("full_name") == full_name:
            return repo
    return None


async def wait_for_hacs_ready(ws: HAWebSocket, timeout: int = 90, poll: float = 3.0) -> bool:
    """Poll `hacs/repositories/list` until it returns success with non-empty
    result. Empty result means HACS hasn't finished its initial repo discovery."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = await ws.call([{"type": "hacs/repositories/list"}])
            if r[0]["success"] and r[0]["result"]:
                return True
        except Exception:
            pass
        await asyncio.sleep(poll)
    return False


async def add_repository(ws: HAWebSocket, full_name: str, category: str = "integration") -> dict:
    """Add a custom repository to HACS. Returns the raw WS response.

    HACS does the add asynchronously — after this returns success, the repo is
    queued for registration. Poll via find_repository(full_name) until the repo
    appears with a numeric .id."""
    r = await ws.call([{
        "type": "hacs/repositories/add",
        "repository": full_name,
        "category": category,
    }])
    return r[0]


async def wait_for_repository_registered(
    ws: HAWebSocket, full_name: str, timeout: int = 60, poll: float = 3.0
) -> dict | None:
    """Poll find_repository until the repo appears with a numeric .id (HACS
    has finished registering it). Returns the repo dict or None on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        repo = await find_repository(ws, full_name)
        if repo and repo.get("id"):
            return repo
        await asyncio.sleep(poll)
    return None


async def download_version(ws: HAWebSocket, repository_id: str, version: str) -> dict:
    """Download a specific git-tag version of a HACS-registered repo. Returns
    the raw WS response. Files land under `<config>/custom_components/<repo>/`.

    Container restart is REQUIRED after download for HA to load the integration —
    HACS doesn't trigger a setup_entry on download alone."""
    r = await ws.call([{
        "type": "hacs/repository/download",
        "repository": str(repository_id),
        "version": version,
    }])
    return r[0]


async def wait_for_downloaded(
    ws: HAWebSocket, full_name: str, version: str, timeout: int = 180, poll: float = 3.0
) -> bool:
    """Poll until the repo shows `installed_version == version`.

    NOTE on field semantics (empirically determined):
      * `installed_version` becoming the target tag IS the "files on disk" signal —
        HACS sets this once it finishes extracting the release zip into
        `<config>/custom_components/<repo>/`.
      * `downloaded` (boolean) means something else in HACS internals — it stays
        None even after a successful download until HA actually loads the
        integration (which requires the post-download container restart). Don't
        gate on it here; gate on `installed_version`.
    """
    deadline = time.monotonic() + timeout
    last_state: tuple = ()
    while time.monotonic() < deadline:
        repo = await find_repository(ws, full_name)
        if repo:
            state = (
                repo.get("installed_version"),
                repo.get("available_version"),
                repo.get("downloaded"),
            )
            if state != last_state:
                print(
                    f"    HACS state: installed_version={state[0]!r} "
                    f"available_version={state[1]!r} downloaded={state[2]}"
                )
                last_state = state
            if state[0] == version:
                return True
        await asyncio.sleep(poll)
    return False
