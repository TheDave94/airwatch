#!/usr/bin/env python3
"""Cleanroom config lint — runs before bootstrap as a fail-fast gate.

Two responsibilities:

1. **HACS pin integrity.** The bytes of assets/hacs-*.zip MUST match the sha256
   recorded in assets/hacs.lock.json. A zip swapped without a lock update fails
   here. The pin is deliberate — see README "The HACS pin — DELIBERATE".

2. **Allowlist honesty.** config/log_allowlist.json may not contain any pattern
   that references migration / migrate / entity_id / registry / config_entry /
   selected_pollutants (case-insensitive). The allowlist is for source-side
   network noise only — silencing migration-related errors defeats Gate C. See
   README "The log allowlist — CAGED on purpose".

Exit code 0 on clean, 1 on any violation.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
FORBIDDEN = re.compile(
    r"\b(migration|migrate|entity_id|registry|config_entry|selected_pollutants)\b",
    re.IGNORECASE,
)


def fail(msg: str) -> None:
    print(f"LINT FAIL: {msg}", file=sys.stderr)


def check_hacs_pin() -> bool:
    lock_path = ROOT / "assets" / "hacs.lock.json"
    if not lock_path.exists():
        fail(f"missing {lock_path}")
        return False
    lock = json.loads(lock_path.read_text())
    zip_path = ROOT / "assets" / lock["zip_filename"]
    if not zip_path.exists():
        fail(f"missing pinned zip {zip_path}")
        return False
    actual = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if actual != lock["sha256"]:
        fail(
            f"HACS zip sha256 mismatch:\n"
            f"  expected: {lock['sha256']}\n"
            f"  actual:   {actual}\n"
            f"  zip:      {zip_path}\n"
            f"  If you deliberately updated HACS, regenerate the lock; see README "
            f"'The HACS pin — DELIBERATE' for when this is appropriate."
        )
        return False
    print(f"  ok   HACS pin {lock['hacs_version']} ({lock['size_bytes']:,} bytes, sha256 match)")
    return True


def check_allowlist() -> bool:
    al_path = ROOT / "config" / "log_allowlist.json"
    if not al_path.exists():
        fail(f"missing {al_path}")
        return False
    al = json.loads(al_path.read_text())
    patterns = al.get("patterns", [])
    if not isinstance(patterns, list):
        fail(f"{al_path}: 'patterns' must be a list")
        return False
    ok = True
    for i, entry in enumerate(patterns):
        if not isinstance(entry, dict):
            fail(f"patterns[{i}] is not an object")
            ok = False
            continue
        regex = entry.get("regex", "")
        reason = entry.get("reason", "")
        added = entry.get("added", "")
        if not regex:
            fail(f"patterns[{i}]: 'regex' missing or empty")
            ok = False
        if not reason or len(reason.strip()) < 8:
            fail(
                f"patterns[{i}] (regex={regex!r}): 'reason' is missing or too short "
                f"(min 8 chars). Document WHY this is allowlisted."
            )
            ok = False
        if not added:
            fail(f"patterns[{i}] (regex={regex!r}): 'added' (ISO date) is missing")
            ok = False
        else:
            try:
                date.fromisoformat(added)
            except ValueError:
                fail(f"patterns[{i}] (regex={regex!r}): 'added' must be ISO YYYY-MM-DD")
                ok = False
        # The big one: regex may not reference any of the forbidden words.
        if regex and FORBIDDEN.search(regex):
            fail(
                f"patterns[{i}] (regex={regex!r}): contains a FORBIDDEN word.\n"
                f"  The allowlist is for source-side network noise ONLY.\n"
                f"  Migration/registry/entity_id/etc are what Gate C exists to catch.\n"
                f"  Silencing them defeats the test. Investigate the root cause; do not "
                f"add to the allowlist."
            )
            ok = False
        # Also check the reason doesn't try to justify the forbidden:
        if reason and FORBIDDEN.search(reason):
            fail(
                f"patterns[{i}]: 'reason' references a FORBIDDEN word. Whatever you "
                f"are trying to allowlist is migration-adjacent. Don't."
            )
            ok = False
    if ok:
        print(f"  ok   log_allowlist clean ({len(patterns)} pattern(s))")
    return ok


def main() -> int:
    print("cleanroom lint:")
    a = check_hacs_pin()
    b = check_allowlist()
    if a and b:
        print("lint OK")
        return 0
    print("\nlint FAILED — see errors above", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
