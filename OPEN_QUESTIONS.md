# AirWatch — open questions

> **ALL RESOLVED 2026-06-18** (fresh-session build). Decisions recorded inline
> below; Q3 + Q4 were flagged to the maintainer and signed off explicitly.

These were decisions, not code. Each blocked part of the fresh-session build.

## Q1 — Repo name — ✅ RESOLVED: `airwatch`
Matches `TheDave94/pollenwatch` (bare name). Local dir `/opt/repos/airwatch`.
GitHub remote `TheDave94/airwatch` (public) created this session; manifest.json +
hacs.json URLs are correct as written.

## Q2 — Open-Meteo air-quality endpoint params — ✅ RESOLVED
Endpoint: `https://air-quality-api.open-meteo.com/v1/air-quality`.
- `hourly` (= `current` mirror): `pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide,european_aqi`
  (literal Open-Meteo variable names — no `_pollen` suffix, unlike PollenWatch).
- `domains=cams_europe` (global returns nulls for several species).
- `past_days=92` (MAX_PAST_DAYS, feeds the self-baselined recent_percentile).
- `forecast_days=5`, `timezone=auto`.
Near-verbatim ADAPT of PollenWatch `OpenMeteoSource._params()`; only the variable
set + the `_API_VAR` mapping change.

## Q3 — Pollutant → device_class + unit map — ✅ RESOLVED (flagged + signed off)
| pollutant | device_class | unit |
|---|---|---|
| PM2.5 | `pm25` | µg/m³ |
| PM10 | `pm10` | µg/m³ |
| NO₂ | `nitrogen_dioxide` | µg/m³ |
| O₃ | `ozone` | µg/m³ |
| SO₂ | `sulphur_dioxide` | µg/m³ |
| CO | **(none)** | **µg/m³** |
| European AQI | `aqi` | (index, no unit) |

**CO decision:** OMIT `device_class`, keep native **µg/m³** + `state_class=measurement`.
Rationale: HA `carbon_monoxide` device_class accepts **ppm only** (`DEVICE_CLASS_UNITS`
rejects µg/m³ → unit-mismatch warning); converting bakes in a T/P assumption and
loses source fidelity. device_class is NOT required for long-term statistics
(`state_class` alone suffices). Keeping µg/m³ also matches the WHO/EU
mass-concentration band basis chosen in Q4. A converted ppm is exposed as a
*provenance-tagged attribute* (assumption: 20 °C / 24.04 L·mol⁻¹ / MW 28.01 g/mol)
for convenience only. The other 5 pollutants keep device_class + µg/m³ (match natively).

## Q4 — Primary threshold standard — ✅ RESOLVED (flagged + signed off)
**WHO 2021 air-quality guidelines = primary health bands; European AQI (EEA/EAQI)
= display/colour scale.** Each band is **provenance-tagged** via a ported
`ThresholdStatus`-analog enum (pollutant_registry) — every band cites
**authority + value + averaging window**; **no invented numbers**. EU legal limit
values (2008/50/EC + 2024 ambient-air directive) and US-EPA AQI breakpoints are
carried as provenance-tagged **alternates**. The averaging-period mismatch (WHO
bands are 24h / annual means; our readings are hourly) is **surfaced as part of
provenance**, not silently ignored — the PollenWatch "expose provenance, don't
assert a verdict" model.

## Q5 — Card framework — ✅ RESOLVED: vanilla-JS bundled
Match PollenWatch (vanilla JS, no build step) for consistency + zero build.
AQI colour ramps per Q4 (EAQI scale).

## Q6 — Land Steiermark access — ✅ RESOLVED: ship disabled-by-default
data.gv.at CKAN API is dead; live HMW is portal-only. Land Steiermark is a
SECONDARY (daily-mean drift anchor). Land the source module but register it
**disabled-by-default / opt-in** until a clean feed exists. Defer the feed work.

## Q7 — Region defaults — ✅ RESOLVED: all CAMS pollutants on for v1
`region_defaults.py` carries the per-region preselection table but does NOT gate
v1; v1 onboarding defaults to **all CAMS pollutants enabled**.
