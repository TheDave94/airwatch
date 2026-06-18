"""AirWatch — constants (deliberately Home-Assistant-free, testable core).

Pollutant keys, source slugs, device names, per-source update intervals,
threshold constants, attribution strings.

TODO: port shape from pollenwatch/.../const.py. Adapt: replace allergen/species
keys with pollutant keys (pm2_5, pm10, no2, o3, so2, co, european_aqi); replace
SOURCE_* slugs with air-quality sources (open_meteo, sensor_community,
land_steiermark); set ATTRIBUTION_* for CAMS/Open-Meteo + Sensor.Community + Land
Steiermark. See OPEN_QUESTIONS.md (endpoint params, device_class map).
"""
