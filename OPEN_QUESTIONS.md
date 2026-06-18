# AirWatch — open questions (resolve before real coding)

These are decisions, not code. Each blocks part of the fresh-session build.

## Q1 — Repo name (BLOCKS: GitHub remote, manifest URLs, hacs.json)
`airwatch` vs `ha-airwatch` vs other. PollenWatch uses the bare name
(`TheDave94/pollenwatch`), so **`airwatch`** is the consistent default.
- Local dir is `/opt/repos/airwatch` (provisional, cheap to rename).
- **No GitHub remote created yet** — awaiting this decision. manifest.json +
  hacs.json currently point at `github.com/TheDave94/airwatch` as a placeholder.

## Q2 — Open-Meteo air-quality endpoint exact params (BLOCKS: open_meteo.py)
Endpoint confirmed: `https://air-quality-api.open-meteo.com/v1/air-quality`.
Decide the exact `hourly=` set + options:
- Candidate `hourly`: `pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide,european_aqi`
  (also available: `us_aqi`, `ammonia`, `dust`, `aerosol_optical_depth`, `uv_index`).
- `domain=cams_europe` (vs global `cams_global`)? `past_days` (backfill for percentile),
  `forecast_days`, `timezone`. Mirror PollenWatch's choices where sensible.

## Q3 — Pollutant → HA device_class + unit map (BLOCKS: sensor.py, pollutant_registry.py)
Proposed (confirm units, esp. CO):
| pollutant | device_class | unit |
|---|---|---|
| PM2.5 | `pm25` | µg/m³ |
| PM10 | `pm10` | µg/m³ |
| NO₂ | `nitrogen_dioxide` | µg/m³ |
| O₃ | `ozone` | µg/m³ |
| SO₂ | `sulphur_dioxide` | µg/m³ |
| CO | `carbon_monoxide` | **µg/m³ or mg/m³?** (Open-Meteo returns µg/m³; HA `carbon_monoxide` class expects ppm — decide convert vs unit override) |
| European AQI | `aqi` | (index, no unit) |

## Q4 — Primary threshold standard (BLOCKS: pollutant_registry.py bands, card)
Which is the canonical band set, with the others as provenance-tagged alternates
(reusing PollenWatch's threshold_status concept):
- **WHO 2021 guidelines** (health-strict), **EU limit values** (legal), or
  **US-AQI breakpoints** (familiar colour ramp)?
- Recommendation to weigh: WHO as primary "health" bands + European AQI as the
  display/colour scale, each tagged by authority. Decide before writing bands.

## Q5 — Card framework (BLOCKS: frontend/airwatch-card.js)
PollenWatch ships a vanilla-JS bundled card. Reuse that approach (no build step)
vs Lit vs custom-button-card template? Default: **match PollenWatch (vanilla JS,
bundled)** for consistency + zero build.

## Q6 — Land Steiermark access path (BLOCKS: land_steiermark.py — lowest priority)
Daily-mean only; data.gv.at CKAN API is dead, live HMW is portal-only. Decide:
scrape the portal map endpoint, use annual archive files, or **ship the source
disabled-by-default** until a clean feed exists. Likely defer (secondary source).

## Q7 — Region defaults (BLOCKS: region_defaults.py)
Which pollutants to preselect per region/country on onboarding (vs select-all).
Lower stakes; can default to "all CAMS pollutants on" for v1.
