"""AirWatch — integration entry point.

Async setup/unload of config entries + config-entry version migrations.

TODO: port from pollenwatch/custom_components/pollenwatch/__init__.py ~as-is.
Adapt: domain string (airwatch), runtime-data dataclass name, migration
version history (AirWatch starts at v1 — drop PollenWatch's v1->v2->v3 chain).
NO logic yet — fresh-session build.
"""
