"""Snapshot helpers — write a structured JSON dump of HA state at a point in
time. Used for the BEFORE / AFTER snapshots that the verifier diffs.

A snapshot is a directory containing:

  config_entries.json   — all airwatch entries (data, options, version, etc.),
                          sourced from .storage/core.config_entries (NOT the WS
                          config_entries/get summary, which omits data/options).
  entity_registry.json  — airwatch entities (entity_id, unique_id, platform, ...)
  device_registry.json  — all devices (filtered to those with airwatch entities)
  states.json           — current state object for each airwatch entity
  logs.txt              — container logs since the snapshot point
  meta.json             — snapshot timestamp, HA version, airwatch version, run_id

The .storage read uses sudo because HA writes its storage files as root inside
the docker container (passwordless sudo is a documented cleanroom prerequisite).
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from .ha_api import HAClient
from .ha_ws import HAWebSocket


def _read_storage_config_entries(config_dir: Path, domain: str | None = None) -> list[dict]:
    """Read .storage/core.config_entries from the bind-mount via sudo cat.
    Returns the entries list, optionally filtered by domain.

    Source of truth for FULL entry data (data, options, version, minor_version,
    unique_id, source, etc). The WS config_entries/get command returns a
    summary shape that omits data/options — useless for migration verification."""
    storage_path = config_dir / ".storage" / "core.config_entries"
    res = subprocess.run(
        ["sudo", "cat", str(storage_path)],
        capture_output=True, text=True, check=True,
    )
    blob = json.loads(res.stdout)
    entries = blob.get("data", {}).get("entries", [])
    if domain:
        entries = [e for e in entries if e.get("domain") == domain]
    return entries


def _iso_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


async def _take_async(client: HAClient, ws: HAWebSocket, out_dir: Path,
                      container_name: str, since: str | None,
                      run_id: str, config_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. AirWatch config entries — from .storage (the source of truth for
    #    data/options/version). The WS config_entries/get returns summaries
    #    only; useless for migration verification.
    full_entries = _read_storage_config_entries(config_dir, domain="airwatch")
    (out_dir / "config_entries.json").write_text(json.dumps(full_entries, indent=2))

    # 2. Entity registry (filter to airwatch)
    all_entities = await ws.entity_registry_list()
    aw_entities = [e for e in all_entities if e.get("platform") == "airwatch"]
    (out_dir / "entity_registry.json").write_text(json.dumps(aw_entities, indent=2))

    # 3. Device registry (full — verifier filters per use)
    devices = await ws.device_registry_list()
    (out_dir / "device_registry.json").write_text(json.dumps(devices, indent=2))

    # 4. States for each airwatch entity
    states = []
    for ent in aw_entities:
        st = client.get_state(ent["entity_id"])
        states.append({"entity_id": ent["entity_id"], "state": st})
    (out_dir / "states.json").write_text(json.dumps(states, indent=2))

    # 5. Container logs since `since` (if provided, else full log)
    log_cmd = ["docker", "logs"]
    if since:
        log_cmd += ["--since", since]
    log_cmd.append(container_name)
    try:
        logs = subprocess.run(
            log_cmd, capture_output=True, text=True, timeout=30, check=False,
        )
        log_text = (logs.stdout or "") + (logs.stderr or "")
    except Exception as e:
        log_text = f"<docker logs failed: {e}>"
    (out_dir / "logs.txt").write_text(log_text)

    # 6. Meta
    ha_info = client.request("/api/config")[1] or {}
    meta = {
        "snapshot_iso": _iso_now(),
        "snapshot_monotonic": time.monotonic(),
        "run_id": run_id,
        "container_name": container_name,
        "ha_version": ha_info.get("version") if isinstance(ha_info, dict) else None,
        "components_count": (
            len(ha_info.get("components", [])) if isinstance(ha_info, dict) else None
        ),
        "aw_entity_count": len(aw_entities),
        "aw_config_entry_count": len(full_entries),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def take_snapshot(
    client: HAClient,
    ws: HAWebSocket,
    out_dir: Path,
    container_name: str,
    run_id: str,
    config_dir: Path,
    since: str | None = None,
) -> dict:
    """Synchronous wrapper. `config_dir` is the HA bind-mount path (its
    .storage/core.config_entries gets read via sudo for full entry data).
    `since` is a docker --since value (RFC3339 or relative like '5m'); None
    = full container log."""
    return asyncio.run(_take_async(client, ws, out_dir, container_name, since, run_id, config_dir))


def load_snapshot(snapshot_dir: Path) -> dict:
    """Read a snapshot dir into a dict of {config_entries, entity_registry,
    device_registry, states, logs, meta}."""
    return {
        "config_entries": json.loads((snapshot_dir / "config_entries.json").read_text()),
        "entity_registry": json.loads((snapshot_dir / "entity_registry.json").read_text()),
        "device_registry": json.loads((snapshot_dir / "device_registry.json").read_text()),
        "states": json.loads((snapshot_dir / "states.json").read_text()),
        "logs": (snapshot_dir / "logs.txt").read_text(),
        "meta": json.loads((snapshot_dir / "meta.json").read_text()),
    }
