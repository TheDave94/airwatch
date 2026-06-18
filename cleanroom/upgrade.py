#!/usr/bin/env python3
"""Clean-room upgrade: rsync HEAD airwatch over the cleanroom's installed
copy, restart, settle, take AFTER snapshot.

Usage:
  python3 cleanroom/upgrade.py cleanroom/runs/<run_id>/
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.ha_api import HAClient  # noqa: E402
from lib.ha_ws import HAWebSocket  # noqa: E402
from lib.snapshot import take_snapshot  # noqa: E402

ROOT = Path(__file__).parent
REPO_ROOT = ROOT.parent


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"FATAL: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def main() -> int:
    if len(sys.argv) != 2:
        die(f"usage: {sys.argv[0]} <run-dir>")
    run_dir = Path(sys.argv[1]).resolve()
    if not (run_dir / "meta.json").exists():
        die(f"{run_dir}/meta.json not found — is this a bootstrap'd run dir?")
    meta = json.loads((run_dir / "meta.json").read_text())
    container = meta["container_name"]
    port = meta["port"]
    base_url = f"http://127.0.0.1:{port}"
    token = (run_dir / "access-token.txt").read_text().strip()
    client = HAClient(base_url, token=token)
    ws = HAWebSocket(base_url, token)

    # 1. rsync HEAD code over the installed copy.
    src = REPO_ROOT / "custom_components" / "airwatch"
    dst = run_dir / "config" / "custom_components" / "airwatch"
    if not src.exists():
        die(f"HEAD source not found at {src}")
    if not dst.exists():
        die(f"installed copy not found at {dst} — did bootstrap complete successfully?")
    # HACS wrote the installed copy as root inside the container — we need
    # sudo to overwrite. Assumes passwordless sudo (the cleanroom-pretag
    # docs document this as a prerequisite).
    log("rsync HEAD (via sudo, files inside bind-mount are root-owned):")
    log(f"  {src} → {dst}")
    res = subprocess.run(
        ["sudo", "rsync", "-a", "--delete", "--exclude", "__pycache__", "--exclude", "*.pyc",
         str(src) + "/", str(dst) + "/"],
        capture_output=True, text=True, check=False,
    )
    if res.returncode != 0:
        die(f"rsync failed (rc={res.returncode}):\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
    log("  ok   HEAD synced")

    # Record the upgrade moment — used as --since for AFTER log capture.
    upgrade_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")

    # 2. Restart container; poll for HA up and airwatch loaded.
    log(f"restarting container {container}")
    subprocess.run(["docker", "restart", container], capture_output=True, check=True)
    log("  polling for HA up...")
    t0 = time.monotonic()
    if not client.wait_until_up(timeout=120):
        die("HA did not come up within 120s post-upgrade restart")
    log(f"  ok   HA up in {time.monotonic() - t0:.1f}s")
    log("  polling for airwatch component loaded...")
    t0 = time.monotonic()
    if not client.wait_for_component("airwatch", timeout=60):
        die(
            "airwatch component did not load within 60s post-upgrade "
            "(gate would fail anyway — surfacing here)"
        )
    log(f"  ok   airwatch loaded in {time.monotonic() - t0:.1f}s")

    # 2b. Wait for ALL airwatch config entries to be in state="loaded".
    #
    # `wait_for_component` returns as soon as ONE entry is loaded — HA's
    # `airwatch in components` flips on the first entry's setup. But HA
    # processes config entries SERIALLY, so the second entry may still be
    # mid-setup. If the settle loop starts polling now, it observes only the
    # first entry's entities, sees them all ready, declares done — and then
    # the second entry's entities arrive AFTER the snapshot, with state=None,
    # cascading into a Gate C "missing state object" failure.
    #
    # Fix: explicitly wait for ALL entries to reach state="loaded" before
    # the settle loop runs.
    log("  polling for all airwatch config entries loaded...")
    t0 = time.monotonic()
    entries_deadline = t0 + 60
    while time.monotonic() < entries_deadline:
        entries = client.list_config_entries(domain="airwatch")
        if entries and all(e.get("state") == "loaded" for e in entries):
            log(
                f"  ok   {len(entries)} entries loaded in "
                f"{time.monotonic() - t0:.1f}s"
            )
            break
        time.sleep(2)
    else:
        die(
            "Not all airwatch config entries reached state='loaded' "
            "within 60s post-upgrade. HA serial-setup may be stuck on one "
            "entry — investigate runner / HA boot. This is infrastructure, "
            "NOT a migration regression.",
            code=10,
        )

    # 3. Settle — poll for refresh, 180s ceiling.
    #
    # Two checks required before declaring complete (avoids a race where the
    # analytics coordinator finishes first, all its few entities have a state,
    # and the loop exits BEFORE the per-source coordinators register their
    # entities — fast CI runners reproduce this consistently):
    #   (a) every currently-loaded aw entity has a non-null state
    #   (b) entity count is STABLE across at least 2 consecutive polls
    #       (i.e. no new entities arrived since the last poll)
    # Both conditions must hold simultaneously.
    #
    # On ceiling-hit: FAIL LOUDLY with a distinct exit code (10), with a
    # message that names this as an infrastructure/timing failure — NOT a
    # migration regression. Never take a snapshot on a partial settle.
    SETTLE_CEILING = 180
    log(
        f"polling for coordinator first-refresh post-upgrade "
        f"(ceiling {SETTLE_CEILING}s, stable-count required)..."
    )
    t0 = time.monotonic()
    deadline = t0 + SETTLE_CEILING
    last_unready = -1
    prev_count = -1
    stable_polls = 0
    while time.monotonic() < deadline:
        all_states = client.all_states()
        aw_states = [
            s for s in all_states
            if s.get("entity_id", "").startswith(
                ("sensor.airwatch_", "binary_sensor.airwatch_")
            )
        ]
        current_count = len(aw_states)
        if current_count == prev_count:
            stable_polls += 1
        else:
            stable_polls = 0
        prev_count = current_count
        if aw_states:
            # "unready" = state is None (coordinator has not run for this
            # entity yet). "unknown" is NOT unready: for recent_percentile
            # sensors on a fresh install with no recorder history, "unknown"
            # is the legitimate populated state. This matches Gate C's
            # semantics in verify.py, which only flags state=None entities
            # as a problem.
            unready = [s for s in aw_states if s.get("state") is None]
            if len(unready) != last_unready:
                log(
                    f"    {current_count - len(unready)}/{current_count} ready "
                    f"(waiting on {len(unready)}; stable_polls={stable_polls})"
                )
                last_unready = len(unready)
            if not unready and stable_polls >= 2:
                log(
                    f"  ok   refresh complete in {time.monotonic() - t0:.1f}s "
                    f"({current_count} entities, count stable across "
                    f"{stable_polls + 1} polls)"
                )
                break
        time.sleep(3)
    else:
        die(
            f"SETTLE TIMEOUT: did not reach stable entity state in "
            f"{SETTLE_CEILING}s (post-upgrade settle). This is an "
            f"infrastructure/timing failure, NOT a migration regression. "
            f"Re-run; if it persists, raise the ceiling or investigate "
            f"runner performance. Snapshot NOT taken — gates will not run.",
            code=10,
        )

    # 4. AFTER snapshot — include only post-upgrade logs.
    log("taking AFTER snapshot:")
    after_dir = run_dir / "snapshots" / "after"
    snap = take_snapshot(client, ws, after_dir, container, meta["run_id"],
                         config_dir=run_dir / "config", since=upgrade_iso)
    log(
        f"  ok   snapshot: {snap['aw_entity_count']} entities, "
        f"{snap['aw_config_entry_count']} entries"
    )

    print(f"\nRUN_DIR: {run_dir}")
    print(f"NEXT:    python3 cleanroom/verify.py {run_dir.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
