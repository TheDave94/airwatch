# AirWatch

> **SCAFFOLD ONLY (2026-06-18) — not yet implemented.** Multi-source outdoor
> air-quality aggregator for Home Assistant (HACS), sibling to
> [PollenWatch](https://github.com/TheDave94/pollenwatch). This repo currently
> holds the skeleton + build plan; the coordinator/sources/registry are a
> fresh-session greenfield build. See `PLAN.md` and `OPEN_QUESTIONS.md`.

## What it will be

A PollenWatch-twin for air quality: combine **Open-Meteo / CAMS** (primary —
free, keyless, hourly, EU-wide µg/m³) with secondary sources (**Sensor.Community**
hyperlocal, **Land Steiermark** official daily-mean) and add cross-source
consensus / divergence / recent-percentile analytics on top. Pollutants:
PM2.5, PM10, NO₂, O₃, SO₂, CO, European AQI.

## Status

| | |
|---|---|
| Skeleton | ✅ created |
| Coordinator / sources / registry | ⛔ not started (fresh session) |
| Governance ported (cleanroom / release-please) | ⛔ stubs only |
| HACS-installable | ⛔ no (version 0.0.0) |

Origin/design rationale lives in the HA-config atlas:
`docs/atlas/air-quality-fusion-roadmap.md` §9 (in the `homeassistant-config` repo).
