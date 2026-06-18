"""AirWatch — SECONDARY source: Sensor.Community (hyperlocal SDS011 cluster).

Per-sensor endpoint: https://data.sensor.community/airrohr/v1/sensor/<id>/  (last
~5 min). Mirrors the in-HA-config REST sensor already deployed for the ventilation
rule, but as an integration source contributing to consensus.

TODO: NEW source (no PollenWatch analog). Implement nearest-sensor pick + fault
rejection (drop 999.9 / out-of-range). Reuse base.py Protocol.
"""
