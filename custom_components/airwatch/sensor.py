"""AirWatch — SensorEntity classes (raw per-source pollutant sensors,
personal/derived, recent-percentile, consensus).

TODO: adapt from pollenwatch/.../sensor.py. KEY DIFFERENCE: per-pollutant
device_class (pm25, pm10, nitrogen_dioxide, ozone, carbon_monoxide,
sulphur_dioxide) + real µg/m³ units, NOT PollenWatch's generic measurement
class. unique_id/name scheme + pruning logic port ~as-is. See OPEN_QUESTIONS.md
for the pollutant->device_class table.
"""
