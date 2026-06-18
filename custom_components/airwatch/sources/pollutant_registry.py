"""AirWatch — CANONICAL_POLLUTANTS registry + threshold/band tables + the
threshold-authority provenance enum.

TODO: REBUILD (replaces pollenwatch/sources/species_registry.py). Define each
pollutant: key, display name, unit (µg/m³ / mg/m³ for CO), HA device_class,
band thresholds. Reuse the PROVENANCE-TIER concept from PollenWatch's
threshold_status -> here it marks band authority: "EU legal limit" vs "WHO 2021
guideline" vs "US-AQI breakpoint" vs "vendor scale". Open questions: pollutant ->
device_class map, which standard is PRIMARY. See OPEN_QUESTIONS.md.
"""
