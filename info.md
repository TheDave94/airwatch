# AirWatch

Multi-source outdoor **air-quality** aggregator for Home Assistant. Combines
independent sources and adds a cross-source analytics layer — so you see not
just *a* number, but **how much the sources agree**, **where the threshold
sits**, and **whose threshold it is**.

- **Open-Meteo / CAMS** (primary, free, keyless) — hourly EU-wide µg/m³.
- **Sensor.Community** (opt-in) — hyperlocal citizen PM2.5/PM10, fault-rejecting.
- **Land Steiermark** (opt-in, drift anchor) — official Austrian stations.
- **Pollutants:** PM2.5, PM10, NO₂, O₃, SO₂, CO, European AQI.
- **Cross-source consensus + divergence**, severity on the 2024 revised
  WHO-aligned EEA index, with multi-authority provenance (WHO 2021 / EU 2024-2881
  / classic-vs-revised EEA).

A bundled **`custom:airwatch-card`** is auto-registered on install (one install,
no separate frontend step) — a glance headline + per-pollutant rows, expanding to
the full multi-authority provenance and cross-source consensus on tap.

## Install

HACS → ⋮ → **Custom repositories** → add `TheDave94/airwatch` as an
**Integration**, install, restart, then **Settings → Devices & Services → Add
Integration → AirWatch**.

MIT-licensed. See the [README](https://github.com/TheDave94/airwatch) for the
full sources, sensors, thresholds/provenance and card documentation.
