#!/usr/bin/env python3
"""Clean up a single cleanroom run: stop + remove its container, preserve the
snapshots / report / logs in runs/<id>/ for post-mortem.

Usage:
  python3 cleanroom/cleanup.py cleanroom/runs/<id>/

Will REFUSE to touch any container whose name is in the protected set. The
PollenWatch protected runtimes (pw-cleanroom, throwaway-pollenwatch on
:8124/:8125) are also listed defensively — this harness must NEVER touch them
even if it is run on the same host.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# Airwatch's own runtime targets are TBD (no dedicated throwaway box yet); the
# pw-* names are listed so this harness can never touch PollenWatch's protected
# containers if it shares a host. The cleanroom-run containers use the
# 'aw-cleanroom-<id>' prefix.
PROTECTED = {"aw-cleanroom", "pw-cleanroom", "throwaway-pollenwatch"}


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <run-dir>", file=sys.stderr)
        return 2
    run_dir = Path(sys.argv[1]).resolve()
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        print(f"{meta_path} not found", file=sys.stderr)
        return 1
    meta = json.loads(meta_path.read_text())
    container = meta["container_name"]
    if container in PROTECTED:
        print(f"REFUSING to clean up protected container '{container}'", file=sys.stderr)
        return 1
    if not container.startswith("aw-cleanroom-"):
        print(f"REFUSING to clean up container '{container}' — name does not match "
              f"the cleanroom-runs prefix 'aw-cleanroom-<id>'", file=sys.stderr)
        return 1
    print(f"stopping container {container}...")
    subprocess.run(["docker", "stop", container], capture_output=True, check=False)
    print(f"removing container {container}...")
    subprocess.run(["docker", "rm", container], capture_output=True, check=False)
    print(f"done. Snapshots / report / logs preserved at {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
