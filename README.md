# AirWatch

Multi-source outdoor **air-quality** aggregator for Home Assistant, distributed
as a [HACS](https://hacs.xyz/) custom repository. Sibling project to
[PollenWatch](https://github.com/TheDave94/pollenwatch) — the same multi-source /
consensus / provenance architecture, re-skinned from pollen onto air-quality
pollutants.

> **Status: v1 in development.** All three data sources work end-to-end
> (Open-Meteo / CAMS primary, plus the opt-in Sensor.Community and Land
> Steiermark secondaries) and the integration sets up with live entities and
> cross-source analytics; the Lovelace card is not finished yet (see
> [Roadmap](#roadmap)). Not yet published to the HACS default store.

## What it does

AirWatch fetches outdoor air-quality data, normalises it across sources, and
layers cross-source analytics on top — so you can see not just *a* number but
**how much the sources agree**, **where the threshold sits**, and **whose
threshold it is**.

- **Primary source — [Open-Meteo](https://open-meteo.com/) / CAMS:** free,
  keyless, hourly, EU-wide µg/m³, with a 92-day backfill and ~5-day forecast.
- **Secondary source — [Sensor.Community](https://sensor.community/)** *(opt-in):*
  hyperlocal citizen PM2.5/PM10 sensors. Auto-discovers the nearest stations (or
  use explicit station IDs), averages the valid ones, and **rejects SDS011 fault
  readings** (the stuck-at-max 999.9) and stale data. Enabling it gives the
  consensus/divergence analytics a second source to cross-check Open-Meteo.
- **Secondary source — Land Steiermark / Austrian network** *(opt-in, drift
  anchor):* the official monitoring stations, reached through the community
  [OGC SensorThings](https://www.ogc.org/standard/sensorthings/) harvest of the
  Austrian feeds (DataCove / API4INSPIRE). This is a **lagged, best-effort feed**
  — a *slow reference / drift anchor*, not a live source. AirWatch picks the
  nearest usable Steiermark station (or an explicit station ID), and every
  reading carries **which station, when, and how old it is**; data older than the
  drift-anchor window is reported as *unavailable* rather than shown as current.
  See [Thresholds & provenance](#thresholds--provenance) for the "expose, don't
  assert" rationale this follows.
- **Pollutants:** PM2.5, PM10, NO₂, O₃, SO₂, CO, and the European AQI index.

## Sensors

Per enabled source, per selected pollutant:

- **Raw concentration** — the source's reported value in its native unit
  (µg/m³), with `state_class: measurement` for long-term statistics. Each
  pollutant carries the correct Home Assistant `device_class` (`pm25`, `pm10`,
  `nitrogen_dioxide`, `ozone`, `sulphur_dioxide`, `aqi`).
- **Recent percentile** — today's daily peak ranked against the trailing ~92
  days (self-baselined from Open-Meteo's backfill).

Across sources, per pollutant:

- **Consensus** — `good` / `elevated` / `high` / `mixed`, with an *n/m* badge of
  how many sources contributed, plus the per-source levels.
- **Divergence** (binary sensor) — flags when sources disagree by more than one
  level.

## Thresholds & provenance

AirWatch **exposes the authority of every band rather than asserting a verdict**
(the model inherited from PollenWatch's `threshold_status`). Two standards are
carried, each tagged:

- **WHO 2021 global air-quality guidelines** — the health overlay. Each raw
  sensor surfaces whether the reading exceeds the WHO guideline *and the
  guideline's averaging window* (24-hour / 8-hour / annual), so the fact that an
  hourly reading is being compared to a longer-mean guideline is visible, not
  hidden.
- **European Air Quality Index (EAQI)** — the display / colour scale (6 bands,
  Good → Extremely poor). AirWatch uses the *classic EEA / Open-Meteo*
  breakpoints so a pollutant's band agrees with the `european_aqi` value on the
  same fetch; the EEA's stricter 2023 revision is the tagged alternate.
- **EU legal limit / target values** (Directive 2008/50/EC) — a tagged overlay
  alongside WHO, kept **distinct** from it: a reading can exceed the WHO
  guideline while remaining under the looser EU limit, and AirWatch shows both
  rather than collapsing them into one verdict.

Each raw sensor carries a `bands` attribute keyed by authority (`eaqi` /
`who_2021` / `eu_limit`), every entry tagged with its **authority + value +
averaging window**. (The US EPA AQI is a reserved authority — not populated in
v1, as it needs per-pollutant ppb/ppm conversion and the piecewise AQI
computation and is US-centric for an EU/CAMS integration.)

### Carbon monoxide units

Open-Meteo reports CO in µg/m³, but Home Assistant's `carbon_monoxide`
`device_class` accepts ppm only. Rather than bake in a temperature/pressure
conversion, AirWatch keeps the **native µg/m³** value (no `device_class`;
`state_class: measurement` preserves statistics) and exposes a converted **ppm**
value as a clearly-labelled attribute (with its conversion assumptions). This
also matches the WHO/EU mass-concentration basis used for CO bands.

## Installation (HACS custom repository)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/TheDave94/airwatch`
   as an **Integration**.
2. Install **AirWatch**, then restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → AirWatch.** Pick your
   location and the pollutants to track; AirWatch probes Open-Meteo coverage
   before finishing.

## Roadmap

| | |
|---|---|
| Open-Meteo / CAMS primary source | ✅ implemented, live-verified |
| Coordinators · config flow · entities (raw / percentile / consensus / divergence) | ✅ implemented |
| Pollutant registry · WHO + EAQI bands · provenance | ✅ implemented |
| Governance (cleanroom no-loss gates · release-please · CI) | ✅ ported |
| Sensor.Community secondary source (fault-rejecting, consensus-enabled) | ✅ implemented, live-verified |
| Land Steiermark drift-anchor source (SensorThings, lag-aware, disabled by default) | ✅ implemented, live-verified |
| Lovelace card (AQI colour ramps) | 🚧 planned |
| Published to HACS | ⛔ not yet |

Design rationale lives in the HA-config atlas:
`docs/atlas/air-quality-fusion-roadmap.md` §9 (in the `homeassistant-config`
repo).

## License

MIT.
