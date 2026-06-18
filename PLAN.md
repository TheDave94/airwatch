# AirWatch — build plan (file-by-file, mapped 1:1 against PollenWatch)

> Scaffold created 2026-06-18. This is the map for the fresh-session implementation.
> Source of truth for the *why*: `homeassistant-config` repo →
> `docs/atlas/air-quality-fusion-roadmap.md` §9.

## Disposition legend
- **PORT** = copy from PollenWatch ~as-is, rename domain/identifiers only (domain-agnostic).
- **ADAPT** = port the shape, change domain-specific content (pollutants vs species).
- **REBUILD** = no usable PollenWatch analog; write fresh.
- **REPLACE** = PollenWatch had N pollen sources; AirWatch swaps in air-quality sources.

## Integration package — `custom_components/airwatch/`

| AirWatch file | From PollenWatch | Disposition | Adapt notes |
|---|---|---|---|
| `__init__.py` | `__init__.py` | PORT | drop the v1→v3 migration chain; AirWatch starts at v1 |
| `manifest.json` | `manifest.json` | ADAPT | domain `airwatch`, repo URL (pending name), version via release-please |
| `const.py` | `const.py` | ADAPT | pollutant keys + source slugs + intervals + CAMS/SC/LS attribution |
| `coordinator.py` | `coordinator.py` | PORT | per-source DUC + `build_coordinators()` factory — unchanged |
| `config_flow.py` | `config_flow.py` | ADAPT | pollutant multiselect vs species; Open-Meteo coverage probe stays |
| `sensor.py` | `sensor.py` | ADAPT | **per-pollutant `device_class` + µg/m³**, not generic measurement |
| `binary_sensor.py` | `binary_sensor.py` | PORT | divergence flag; bands from threshold tables |
| `analytics.py` | `analytics.py` | PORT | consensus/divergence/percentile — pure, unchanged math |
| `diagnostics.py` | `diagnostics.py` | PORT | redact keys |
| `websocket_api.py` | `websocket_api.py` | PORT | rename WS command → `airwatch/config` |
| `region_defaults.py` | `region_defaults.py` | REBUILD | which pollutants matter per region |
| `quality_scale.yaml` | `quality_scale.yaml` | PORT | re-assess each rule |
| `strings.json` / `translations/*` | same | ADAPT | step labels, pollutant names |
| `sources/__init__.py` | `sources/__init__.py` | PORT | |
| `sources/base.py` | `sources/base.py` | PORT | `PollenSource→AirQualitySource`, `AllergenSeries→PollutantSeries` |
| `sources/open_meteo.py` | `sources/open_meteo.py` | ADAPT | **PRIMARY**; air-quality `hourly=` params |
| `sources/sensor_community.py` | — | REBUILD | secondary; nearest-sensor + 999.9 fault reject |
| `sources/land_steiermark.py` | — | REBUILD | secondary; daily-mean drift anchor, low-freshness |
| `sources/pollutant_registry.py` | `sources/species_registry.py` | REBUILD | pollutants + band tables + authority-provenance enum |
| `frontend/airwatch-card.js` | `frontend/pollenwatch-card.js` | REBUILD | AQI colour ramps |
| `frontend/icons/*` | `frontend/icons/*` (24 species) | REBUILD | ~6 pollutant icons |
| `brand/*` | `brand/*` | REBUILD | new artwork |

Dropped (PollenWatch pollen sources with no AirWatch equivalent):
`polleninformation.py`, `dwd.py`, `meteoswiss.py`, `epin.py`, `google.py` →
**REPLACED** by `open_meteo` (reused) + `sensor_community` + `land_steiermark`.

## Governance — PORT ~as-is (domain-agnostic, highest-value reuse)

| AirWatch path | From PollenWatch | Notes |
|---|---|---|
| `.github/workflows/cleanroom.yml` | same | no-loss Gates A–D; seed baseline tag once v1 ships |
| `.github/workflows/prerelease-gate.yml` | same | Tier-1 smoke; throwaway-HA target |
| `.github/workflows/release-please.yml` | same | needs `RELEASE_APP_*` secrets on new repo |
| `.github/workflows/lint.yml` / `validate.yml` | same | Ruff+pytest / hassfest |
| `cleanroom/**` | `cleanroom/**` | whole harness ports; adapt domain + allowlist |
| `hacs.json` | same | ✅ already written (structural) |
| `pyproject.toml`, `release-please-config.json`, `.release-please-manifest.json` | same | adapt names; seed manifest once versioned |
| `requirements-*.txt`, `Makefile` | same | port |
| `tests/**` | `tests/**` | port suite structure (conftest + unit + e2e) |

## Build order (fresh session)
1. `base.py` + `pollutant_registry.py` (the contract + the data model). 
2. `open_meteo.py` (primary source) → smoke against the live endpoint.
3. `coordinator.py` + `__init__.py` + `config_flow.py` (one-source vertical slice).
4. `sensor.py` (+ device_class map) → first live entities.
5. `analytics.py` + `binary_sensor.py` (multi-source) → add `sensor_community`, `land_steiermark`.
6. Port governance (cleanroom/release-please/workflows) → cut v1 → HACS.
