#!/usr/bin/env python3
"""Generate a FAITHFUL AirWatch fixture (states.json) for the screenshot harness.

The attributes here are NOT hand-written — they are computed by the integration's
own shipped functions (`level_for_value`, `band_provenance`, `consensus`,
`level_label`). That means if the band thresholds or consensus logic ever change,
re-running this script regenerates correct data automatically. Never fabricate
attribute values by hand; extend the SCENARIO below and let the real code derive
the rest.

The scenario uses a synthetic, location-free home and genuine source-coverage
shapes (Sensor.Community is PM-only; european_aqi is Open-Meteo-only; carbon
monoxide honestly has no EAQI band authority). One pollutant (pm2_5) is tuned to
a real divergence (a clean regional value vs. a local sensor spike) so the card's
divergence/mixed state is exercised truthfully.

Run:  python3 gen.py     (writes states.json next to this file)
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from custom_components.airwatch.sources.pollutant_registry import (  # noqa: E402
    level_for_value,
    band_provenance,
)
from custom_components.airwatch.analytics import consensus, level_label  # noqa: E402

OUT = Path(__file__).resolve().parent / "states.json"

SRC_LABEL = {
    "open_meteo": "Open-Meteo",
    "sensor_community": "Sensor.Community",
    "land_steiermark": "Land Steiermark",
}
UNIT = "µg/m³"

# pollutant -> {source: value µg/m³}. Coverage mirrors reality:
#   Sensor.Community = PM only; Land = everything but european_aqi; Open-Meteo = all.
SCEN = {
    "pm2_5":            {"open_meteo": 4,   "sensor_community": 135, "land_steiermark": 16},  # divergence: clean 4 vs local spike 135
    "pm10":             {"open_meteo": 44,  "sensor_community": 51,  "land_steiermark": 47},  # 3-source agreement, elevated
    "nitrogen_dioxide": {"open_meteo": 58,  "land_steiermark": 49},
    "ozone":            {"open_meteo": 132, "land_steiermark": 119},
    "sulphur_dioxide":  {"open_meteo": 9,   "land_steiermark": 12},
    "carbon_monoxide":  {"open_meteo": 210, "land_steiermark": 185},  # honest: band_provenance has no EAQI authority
    "european_aqi":     {"open_meteo": 63},
}
# global ceilings: how many sources GLOBALLY can cover each pollutant
MAXP = {"pm2_5": 3, "pm10": 3, "nitrogen_dioxide": 2, "ozone": 2,
        "sulphur_dioxide": 2, "carbon_monoxide": 2, "european_aqi": 1}

NOW = "2026-06-19T17:00:00+00:00"

states = {}
report = []
for p, srcs in SCEN.items():
    levels = {}
    for src, val in srcs.items():
        lvl = level_for_value(p, float(val))
        levels[src] = lvl
        states[f"sensor.airwatch_{src}_{p}"] = {
            "entity_id": f"sensor.airwatch_{src}_{p}",
            "state": str(val),
            "last_changed": NOW, "last_updated": NOW,
            "attributes": {
                "unit_of_measurement": UNIT,
                "level": lvl, "level_label": level_label(lvl),
                "bands": band_provenance(p, float(val)),
                "friendly_name": f"AirWatch {SRC_LABEL[src]} {p}",
            },
        }
    cr = consensus(levels, MAXP[p])
    states[f"sensor.airwatch_analytics_{p}_consensus"] = {
        "entity_id": f"sensor.airwatch_analytics_{p}_consensus",
        "state": cr.state or "unknown",
        "last_changed": NOW, "last_updated": NOW,
        "attributes": {
            "source_levels": cr.source_levels, "source_count": cr.source_count,
            "max_possible_sources": cr.max_possible, "level": cr.level,
            "level_label": level_label(cr.level) if cr.level is not None else cr.state,
            "friendly_name": f"AirWatch {p} consensus",
        },
    }
    states[f"binary_sensor.airwatch_analytics_{p}_divergence"] = {
        "entity_id": f"binary_sensor.airwatch_analytics_{p}_divergence",
        "state": "on" if cr.diverged else "off",
        "last_changed": NOW, "last_updated": NOW,
        "attributes": {"device_class": "problem", "friendly_name": f"AirWatch {p} divergence"},
    }
    report.append(
        f"  {p:18} levels={levels} -> consensus={cr.state} "
        f"count={cr.source_count}/{cr.max_possible} diverged={cr.diverged}"
    )

OUT.write_text(json.dumps(states, indent=1))
print(f"WROTE {len(states)} entities -> {OUT.relative_to(REPO_ROOT)}")
print("\n".join(report))
# sanity: CO must have NO EAQI authority in its bands
co_bands = states["sensor.airwatch_open_meteo_carbon_monoxide"]["attributes"]["bands"]
assert not any(k.startswith("eaqi") for k in co_bands), "CO unexpectedly has an EAQI band!"
print("\nCO band authorities:", list(co_bands.keys()), " (correctly no eaqi_*)")
