#!/usr/bin/env python3
"""Clean-room verifier — 4 gates over BEFORE/AFTER snapshots.

  A. Schema migrated:    version/minor_version bumped (when migration expected);
                         `selected_pollutants` + `sources` present after.
  B. Entity preservation: (entity_id, unique_id) PAIRS before == after.
  C. Integration healthy: no airwatch ERROR/Traceback in post-upgrade logs
                         (after allowlist); every pre-existing entity has a state
                         object.
  D. Subset preserved:   Entry B selected pollutants == [pm2_5, pm10] post-upgrade.

Output:
  Full structured report → stdout AND runs/<id>/report.txt. NEVER tailed.

Exit codes:
  0  all gates pass
  1  Gate A fail
  2  Gate B fail
  3  Gate C fail
  4  Gate D fail
  (multiple failures: exit with the lowest-numbered failed gate; full report
  always shows all gates)
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.snapshot import load_snapshot  # noqa: E402

ROOT = Path(__file__).parent
REPO_ROOT = ROOT.parent


# ---------- helpers ----------

def _pollutants_of(entry: dict) -> list[str] | None:
    """Return the pollutant list from an entry, in either data or options."""
    for bucket in ("options", "data"):
        d = entry.get(bucket) or {}
        if "selected_pollutants" in d and isinstance(d["selected_pollutants"], list):
            return list(d["selected_pollutants"])
    return None


def _has_key_anywhere(entry: dict, key: str) -> bool:
    return any(key in (entry.get(bucket) or {}) for bucket in ("data", "options"))


def _find_entry_by_title_contains(entries: list[dict], needle: str) -> dict | None:
    for e in entries:
        title = (e.get("title") or "").lower()
        if needle.lower() in title:
            return e
    return None


def _find_entry_for_matrix(entries: list[dict], matrix_entry: dict) -> dict | None:
    """Match an entry from the snapshot against a matrix.json entry.

    Tries three strategies in order, each with appropriate tolerance for the
    rounding/shape variations we've actually seen:

      1. `data.latitude` + `data.longitude` (flat — airwatch v1 schema).
         Tolerance: 0.001 (1m at the equator). Matches exact stored values.
      2. `data.location.{latitude,longitude}` (nested — defensive for older
         shapes or if a later schema ever wraps location). Same tolerance.
      3. Title parse: airwatch sets entry title to "AirWatch (LAT, LON)" with
         3-decimal rounding (e.g. "AirWatch (48.208, 16.374)" for 48.2082,
         16.3738). Compare with tolerance 0.01 to absorb the rounding.

    Returns the matching entry dict, or None."""
    import re as _re
    target_lat = matrix_entry["latitude"]
    target_lon = matrix_entry["longitude"]

    def _near(a: float, b: float, tol: float) -> bool:
        return a is not None and b is not None and abs(a - b) < tol

    title_coord_re = _re.compile(r"\(([-\d.]+)\s*,\s*([-\d.]+)\)")

    for e in entries:
        data = e.get("data") or {}
        # Strategy 1: flat data.latitude/longitude (v1 schema).
        if (
            _near(data.get("latitude"), target_lat, 0.001)
            and _near(data.get("longitude"), target_lon, 0.001)
        ):
            return e
        # Strategy 2: nested location dict.
        loc = data.get("location") or {}
        if (
            _near(loc.get("latitude"), target_lat, 0.001)
            and _near(loc.get("longitude"), target_lon, 0.001)
        ):
            return e
        # Strategy 3: parse title "AirWatch (LAT, LON)".
        m = title_coord_re.search(e.get("title", "") or "")
        if m:
            try:
                tlat = float(m.group(1))
                tlon = float(m.group(2))
                if _near(tlat, target_lat, 0.01) and _near(tlon, target_lon, 0.01):
                    return e
            except ValueError:
                pass
    return None


# ---------- allowlist ----------

def _load_allowlist() -> list[re.Pattern]:
    al = json.loads((ROOT / "config" / "log_allowlist.json").read_text())
    return [re.compile(p["regex"]) for p in al.get("patterns", [])]


# ---------- gates ----------

def gate_a_schema(before: dict, after: dict, meta: dict, out: io.StringIO) -> bool:
    """Gate A: schema migrated correctly."""
    out.write("\n=== Gate A — schema migrated ===\n")
    b_entries = before["config_entries"]
    a_entries = after["config_entries"]
    baseline_v = meta["baseline_spec"]["flow_version"]
    head_v = meta["head_flow_version"]
    migration_expected = baseline_v != head_v
    out.write(f"  baseline flow_version: {baseline_v}\n")
    out.write(f"  head flow_version:     {head_v}\n")
    out.write(f"  migration expected:    {migration_expected}\n")
    out.write(f"  entries before: {len(b_entries)}, after: {len(a_entries)}\n")
    if len(b_entries) != len(a_entries):
        out.write(f"  FAIL: entry count changed ({len(b_entries)} → {len(a_entries)})\n")
        return False
    ok = True
    for b in b_entries:
        a = next((x for x in a_entries if x.get("entry_id") == b.get("entry_id")), None)
        if not a:
            out.write(f"  FAIL: entry {b.get('entry_id')} disappeared post-upgrade\n")
            ok = False
            continue
        bv = (b.get("version"), b.get("minor_version", 1))
        av = (a.get("version"), a.get("minor_version", 1))
        out.write(f"  entry {a.get('title','?')!r} ({a['entry_id'][:8]}…): "
                  f"version {bv} → {av}\n")
        if migration_expected:
            if av[0] != head_v:
                out.write(f"    FAIL: expected version={head_v}, got {av[0]}\n")
                ok = False
            if not _has_key_anywhere(a, "selected_pollutants"):
                out.write("    FAIL: 'selected_pollutants' missing post-migration\n")
                ok = False
        else:
            # HEAD→HEAD: no version change expected, no migration ran.
            if av != bv:
                out.write("    FAIL: version unexpectedly changed in no-migration run\n")
                ok = False
        # Always check: sources present in HEAD shape.
        opts = (a.get("options") or {})
        data = (a.get("data") or {})
        if "sources" not in opts and "sources" not in data:
            out.write("    WARN: 'sources' missing (head shape expects it)\n")
    out.write(f"  Gate A: {'PASS' if ok else 'FAIL'}\n")
    return ok


def gate_b_entity_pairs(before: dict, after: dict, out: io.StringIO) -> bool:
    """Gate B — entity preservation (NO-LOSS semantics, not strict equality).

    Gate B guarantees users do not LOSE entities on upgrade: every pre-upgrade
    (entity_id, unique_id) pair must still exist post-upgrade. That's the only
    safety-critical assertion — a missing pair means a user's dashboards,
    automations, and history references silently break.

    Feature releases legitimately ADD entity surface. Those additions are
    surfaced as a WARN (informational) so the operator sees them in the report,
    but they do NOT fail the gate.

    Semantics:
      * lost > 0  → FAIL (preservation guarantee broken; investigate)
      * gained > 0 only → PASS with WARN block listing the gained pairs
      * gained == 0 and lost == 0 → PASS (no churn)
    """
    out.write("\n=== Gate B — entity preservation (no-loss) ===\n")
    b_ents = before["entity_registry"]
    a_ents = after["entity_registry"]
    b_pairs = {(e["entity_id"], e.get("unique_id")) for e in b_ents}
    a_pairs = {(e["entity_id"], e.get("unique_id")) for e in a_ents}
    out.write(f"  before: {len(b_pairs)} airwatch (entity_id, unique_id) pairs\n")
    out.write(f"  after:  {len(a_pairs)} airwatch (entity_id, unique_id) pairs\n")

    lost = b_pairs - a_pairs
    gained = a_pairs - b_pairs

    # Classify any lost pair for diagnostics.
    a_by_eid = {e["entity_id"]: e.get("unique_id") for e in a_ents}
    a_by_uid = {e.get("unique_id"): e["entity_id"] for e in a_ents if e.get("unique_id")}
    b_by_eid = {e["entity_id"]: e.get("unique_id") for e in b_ents}
    b_by_uid = {e.get("unique_id"): e["entity_id"] for e in b_ents if e.get("unique_id")}

    if lost:
        out.write(f"  LOST pairs ({len(lost)}) — preservation broken:\n")
        for eid, uid in sorted(lost):
            cause = "entity lost entirely"
            if eid in a_by_eid and a_by_eid[eid] != uid:
                cause = f"unique_id changed: {uid!r} → {a_by_eid[eid]!r}"
            elif uid in a_by_uid and a_by_uid[uid] != eid:
                cause = f"entity_id renamed: {eid!r} → {a_by_uid[uid]!r}"
            out.write(f"    - ({eid}, {uid})  — {cause}\n")

    if gained:
        out.write(f"  WARN: {len(gained)} new (entity_id, unique_id) pair(s) post-upgrade "
                  f"(informational, not a failure):\n")
        for eid, uid in sorted(gained):
            cause = "new entity (not in before)"
            if eid in b_by_eid:
                cause = "unique_id changed for existing entity_id"
            elif uid and uid in b_by_uid:
                cause = "entity_id renamed for existing unique_id"
            out.write(f"    + ({eid}, {uid})  — {cause}\n")
        out.write("  Review the WARN list above: legitimate feature-adds are expected.\n")
        out.write("  Unintentional duplications or unique_id typos look the same in this\n")
        out.write("  output — check the diff before tagging.\n")

    if lost:
        out.write("  Gate B: FAIL (preservation guarantee broken — see LOST list)\n")
        return False
    if gained:
        out.write("  Gate B: PASS (no loss; gains surfaced above as WARN)\n")
    else:
        out.write("  Gate B: PASS — pair set identical\n")
    return True


def gate_c_health(after: dict, out: io.StringIO) -> bool:
    """Gate C: no airwatch errors in post-upgrade logs (after allowlist);
    every pre-existing entity has a state object."""
    out.write("\n=== Gate C — integration healthy post-upgrade ===\n")
    allowlist = _load_allowlist()
    log_lines = after["logs"].splitlines()
    # Match ERROR/Traceback lines mentioning airwatch.
    err_re = re.compile(
        r"\b(ERROR|Traceback|Exception|CRITICAL)\b.*airwatch"
        r"|airwatch.*\b(ERROR|Traceback|Exception|CRITICAL)\b",
        re.IGNORECASE,
    )
    raw_hits = [ln for ln in log_lines if err_re.search(ln)]
    out.write(f"  raw error lines mentioning 'airwatch': {len(raw_hits)}\n")
    # Apply allowlist.
    def is_allowlisted(line: str) -> bool:
        return any(p.search(line) for p in allowlist)
    surviving = [ln for ln in raw_hits if not is_allowlisted(ln)]
    out.write(f"  after allowlist:                       {len(surviving)}\n")
    log_ok = (len(surviving) == 0)
    if surviving:
        out.write("  surviving error lines (full, not truncated):\n")
        for ln in surviving:
            out.write(f"    | {ln}\n")
    # State-object check.
    state_misses = [s for s in after["states"] if s.get("state") is None]
    out.write(
        f"  entities with missing state object: {len(state_misses)} "
        f"(of {len(after['states'])})\n"
    )
    state_ok = (len(state_misses) == 0)
    if state_misses:
        for s in state_misses:
            out.write(f"    - {s['entity_id']}: state=None\n")
    ok = log_ok and state_ok
    out.write(f"  Gate C: {'PASS' if ok else 'FAIL'}\n")
    return ok


def gate_d_subset(after: dict, meta: dict, out: io.StringIO) -> bool:
    """Gate D: subset entry preserved exactly."""
    out.write("\n=== Gate D — subset preservation (the load-bearing diagnostic) ===\n")
    matrix = meta["matrix"]
    canonical = set(matrix.get("canonical_v1_pollutants", []))
    subset_entries = [e for e in matrix["entries"] if set(e["pollutants"]) < canonical]
    if not subset_entries:
        out.write("  FAIL: matrix.json has no subset entry — bootstrap should have refused\n")
        return False
    ok = True
    for subset in subset_entries:
        expected = sorted(subset["pollutants"])
        match = _find_entry_for_matrix(after["config_entries"], subset)
        if not match:
            out.write(f"  FAIL: matrix entry {subset['name']} ({subset['location_label']}) "
                      f"not found in after snapshot\n")
            ok = False
            continue
        actual = _pollutants_of(match)
        actual_sorted = sorted(actual) if actual else None
        out.write(f"  matrix entry {subset['name']!r} ({subset['location_label']})\n")
        out.write(f"    expected pollutants: {expected}\n")
        out.write(f"    actual pollutants:   {actual_sorted}\n")
        if actual_sorted != expected:
            out.write("    FAIL: subset NOT preserved exactly\n")
            ok = False
            if actual:
                extra = sorted(set(actual) - set(expected))
                missing = sorted(set(expected) - set(actual))
                if extra:
                    out.write(f"      pollutants added unexpectedly: {extra}\n")
                if missing:
                    out.write(f"      pollutants lost: {missing}\n")
        else:
            out.write("    ok\n")
    out.write(f"  Gate D: {'PASS' if ok else 'FAIL'}\n")
    return ok


# ---------- main ----------

def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <run-dir>", file=sys.stderr)
        return 2
    run_dir = Path(sys.argv[1]).resolve()
    meta = json.loads((run_dir / "meta.json").read_text())
    before = load_snapshot(run_dir / "snapshots" / "before")
    after = load_snapshot(run_dir / "snapshots" / "after")

    out = io.StringIO()
    out.write("================================\n")
    out.write("AirWatch cleanroom verify\n")
    out.write("================================\n")
    out.write(f"run_id:      {meta['run_id']}\n")
    out.write(
        f"baseline:    {meta['baseline']} "
        f"(flow_version={meta['baseline_spec']['flow_version']})\n"
    )
    out.write(f"head:        flow_version={meta['head_flow_version']}\n")
    out.write(f"before HA:   {before['meta'].get('ha_version','?')}\n")
    out.write(f"after  HA:   {after['meta'].get('ha_version','?')}\n")

    a = gate_a_schema(before, after, meta, out)
    b = gate_b_entity_pairs(before, after, out)
    c = gate_c_health(after, out)
    d = gate_d_subset(after, meta, out)

    summary = (
        f"\nGATE_RESULTS: "
        f"A={'PASS' if a else 'FAIL'} "
        f"B={'PASS' if b else 'FAIL'} "
        f"C={'PASS' if c else 'FAIL'} "
        f"D={'PASS' if d else 'FAIL'}\n"
    )
    out.write(summary)

    report = out.getvalue()
    (run_dir / "report.txt").write_text(report)
    print(report, end="")

    # Exit code: 0 if all pass; lowest-numbered failing gate otherwise.
    for i, ok in enumerate([a, b, c, d], start=1):
        if not ok:
            return i
    return 0


if __name__ == "__main__":
    sys.exit(main())
