# AirWatch clean-room migration test

Repeatable, mostly-unattended end-to-end test that proves a previously-released version of AirWatch upgrades cleanly to HEAD with **no entity churn, no schema regressions, no silent option resets**.

**Run before tagging a release. ~5 min wall-clock. The verifier output IS the gate.**

```
make cleanroom-pretag
```

Ported ~as-is from PollenWatch's cleanroom harness (it is domain-agnostic) with `pollenwatch → airwatch` and `species/allergens → pollutants` throughout.

> **NOTE — AirWatch has no released baseline tag yet.** The harness installs a *baseline* release first, then upgrades to HEAD. Until v1 ships there is nothing to migrate *from*: `cleanroom/config/pinned_release.json` carries a `TBD` placeholder. Seed the first real tag there (and `make` it the `default_baseline`) once v1 is released. The runtime container name prefix is `aw-cleanroom-<timestamp>` and the host **port is a TBD placeholder (8200)** — it deliberately does NOT reuse PollenWatch's protected `pw-cleanroom` (:8125) or `throwaway-pollenwatch` (:8124). Pick AirWatch's own dedicated port once a live runtime exists.

Sole prerequisite: a fine-grained GitHub PAT (read-only, public-repo) at `~/.config/airwatch-cleanroom/github-pat`. See **First-time setup** below.

## What it does

1. **Bootstrap** (`cleanroom/bootstrap.py`)
   - Mints a fresh run directory under `cleanroom/runs/<timestamp>/`.
   - Pre-seeds a fresh HA config dir: HACS extracted in place; `.storage/core.config_entries` written with a HACS entry holding your pre-seeded GitHub PAT. **No device-flow wall.**
   - Starts a new HA container `aw-cleanroom-<timestamp>` on the placeholder port against that config dir.
   - Walks the onboarding API (creates owner, sets core config to AT / Vienna / Graz coords, mints long-lived access token). **No browser.**
   - Polls for HACS ready, adds `TheDave94/airwatch`, downloads the pinned baseline version.
   - Restarts container; creates the two diagnostic config entries from `cleanroom/config/matrix.json`:
     - **Entry A** — Munich, all canonical pollutants.
     - **Entry B** — Graz, subset `[pm2_5, pm10]`.
   - Polls until every airwatch entity has its first real state (180s ceiling; SETTLE TIMEOUT on ceiling-hit).
   - Takes a BEFORE snapshot under `runs/<timestamp>/snapshots/before/`.

2. **Upgrade** (`cleanroom/upgrade.py`)
   - rsyncs HEAD `custom_components/airwatch/` over the cleanroom's installed copy (`--delete` mirrors HEAD exactly).
   - Restarts the container; polls until HA up; polls until coordinator-refresh-complete.
   - Takes AFTER snapshot.

3. **Verify** (`cleanroom/verify.py`)
   - Runs the 4 gates (below).
   - Prints the report in full. **Never piped through `tail` / `head`** — verification output is the signal.
   - Exits 0 if all gates pass; exits with the failed gate's number otherwise.

## Gates

| Gate | Asserts |
|---|---|
| **A. Schema migrated** | Entry `version` / `minor_version` correctly bumped (when migration expected); `selected_pollutants` present post-upgrade; `sources` present. (HEAD→HEAD smoke: version unchanged — passes trivially.) |
| **B. Entity preservation** | **`(entity_id, unique_id)` PAIRS** before == after for every `platform=="airwatch"` entity. **Pair equality is load-bearing** — a changed unique_id with entity_id surviving by luck is exactly the failure mode this guards against. |
| **C. Integration healthy** | No `ERROR.*airwatch` / `Traceback.*airwatch` lines in container logs since the upgrade timestamp (after allowlist). Every pre-existing entity has a state object (`state.state == "unavailable"` is OK; missing state object is not). |
| **D. Subset preserved** | Entry B's selected pollutants is **exactly** `["pm2_5", "pm10"]` post-upgrade. The diagnostic that distinguishes "migration preserved selection" from "reset to default-all." |

## The HACS pin — DELIBERATE, not tracked

`cleanroom/assets/hacs-*.zip` is **vendored on purpose** (seed it when the harness first runs end-to-end). The cleanroom test is about **our** migration story — that AirWatch users on our last release can upgrade to HEAD. It is **not** a HACS-version compatibility test.

- **Do NOT routinely refresh the HACS zip** to track upstream HACS releases. That's noise that adds churn without signal.
- **Refresh ONLY if** a HACS upstream change has materially broken bootstrap (a renamed WS command, a new storage-key requirement, a new onboarding step we have to walk). The trigger is a broken bootstrap, not a calendar date.
- The pin is recorded in `assets/hacs.lock.json` (version + sha256). Replacing the zip without updating the lock fails `lint.py`.

## The log allowlist — CAGED on purpose

`cleanroom/config/log_allowlist.json` is the one knob in this system that could quietly defeat Gate C. **It is caged.**

- The allowlist exists for **source-side network noise ONLY** — an air-quality API returning a 5xx, a transient connection error to Open-Meteo / Sensor.Community / Land Steiermark.
- **NEVER allowlist anything matching** (case-insensitive): `migration`, `migrate`, `entity_id`, `registry`, `config_entry`, `selected_pollutants`. These describe what the gate is built to catch. **Silencing them defeats the test.**
- `lint.py` enforces this rule. It runs before bootstrap and aborts with the exact pattern that violated the rule.
- Every allowlist entry requires a `reason` (free-form) and an `added` ISO date. Lint enforces non-empty.

The allowlist starts empty. It earns entries only with reason + date + a clean pass through lint.

## First-time setup

1. **Generate the GitHub PAT** (one-time per 90 days):
   - GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.
   - Token name: `airwatch-cleanroom`. Expiration: 90 days. Resource owner: your account.
   - Repository access: **Public repositories (read-only)** — no other scope needed.

2. **Store the PAT** (one-time, never commit, never echo):
   ```bash
   mkdir -p ~/.config/airwatch-cleanroom
   chmod 700 ~/.config/airwatch-cleanroom
   # Paste the PAT directly into the file via $EDITOR — NOT `echo $PAT > ...`.
   $EDITOR ~/.config/airwatch-cleanroom/github-pat
   chmod 600 ~/.config/airwatch-cleanroom/github-pat
   ```

3. **Install runtime deps** (one-time):
   ```bash
   python3 -m venv ~/.cache/airwatch-cleanroom/venv
   ~/.cache/airwatch-cleanroom/venv/bin/pip install -r requirements-cleanroom.txt
   ```

4. **Confirm docker + the placeholder port free** (TBD — pick AirWatch's own port):
   ```bash
   docker --version
   ss -tln | grep ":8200" || echo "port 8200 free"
   ```

## Running

Full cycle (once a baseline is seeded):
```bash
make cleanroom-pretag
```

Override baseline:
```bash
make cleanroom-pretag BASELINE=v1.0.0
```

Step-by-step (debugging):
```bash
python3 cleanroom/bootstrap.py                    # creates runs/<ts>/, prints the run dir
python3 cleanroom/upgrade.py cleanroom/runs/<ts>/
python3 cleanroom/verify.py cleanroom/runs/<ts>/
```

Cleanup after a run:
```bash
python3 cleanroom/cleanup.py cleanroom/runs/<ts>/   # stops container, leaves snapshots/report
docker ps -a --filter "name=aw-cleanroom-" --format '{{.Names}}' | grep -v '^aw-cleanroom$' | xargs -r docker rm -f
```

(The `grep -v '^aw-cleanroom$'` guard, plus `cleanup.py`'s PROTECTED set, prevent touching any protected container.)

## Baseline ↔ flow-version map

The HA config-entry version the baseline airwatch installs at, and the field name that version's config-flow expects. Used by bootstrap to submit the right field name. Maintained in `cleanroom/config/pinned_release.json`:

| AirWatch tag | Flow `VERSION` | Pollutant field |
|---|---|---|
| `TBD` (seed at v1) | 1 | `selected_pollutants` |

## Operational safety — what this system does NOT touch

The harness is **physically separated** from any maintainer-operated runtime:

| Layer | Protected (don't touch) | This system |
|---|---|---|
| Container name | `pw-cleanroom`, `throwaway-pollenwatch` (PollenWatch) | `aw-cleanroom-<timestamp>` |
| Host port | 8125, 8124 (PollenWatch) | **8200 (TBD placeholder)** |
| Bind-mount | (PollenWatch's) | `cleanroom/runs/<timestamp>/config/` |

`cleanup.py` and `make cleanroom-cleanup-all` are name-prefix-filtered to `aw-cleanroom-` and refuse the protected set, so they can never touch PollenWatch's containers even on a shared host.

## File layout

```
cleanroom/
├── README.md                    (this file)
├── bootstrap.py                 (seed → boot → onboarding → HACS install → 2 entries → BEFORE snapshot)
├── upgrade.py                   (rsync HEAD → restart → settle → AFTER snapshot)
├── verify.py                    (4 gates → structured report → exit code)
├── lint.py                      (HACS pin + allowlist sanity; runs first in bootstrap)
├── cleanup.py                   (stop run's container; keep snapshots)
├── assets/                      (TBD — vendor the HACS zip + lock when first running end-to-end)
│   ├── hacs-<v>.zip
│   └── hacs.lock.json
├── config/
│   ├── pinned_release.json      (baseline tag + flow-version map; TBD until v1)
│   ├── matrix.json              (the 2 entries; subset entry is non-optional)
│   └── log_allowlist.json       (caged; lint enforces honesty)
├── lib/
│   ├── __init__.py
│   ├── ha_api.py                (REST helpers)
│   ├── ha_ws.py                 (WS client; max_size=20MiB pinned)
│   ├── ha_flow.py               (config_flow + options_flow over REST)
│   ├── hacs.py                  (HACS WS commands)
│   ├── onboarding.py            (first-user via /api/onboarding/*)
│   └── snapshot.py              (config_entries + entity_registry + device_registry + states + logs)
└── runs/                        (gitignored — per-run output dirs)
```
