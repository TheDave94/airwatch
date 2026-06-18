"""AirWatch — per-source DataUpdateCoordinator + build_coordinators() factory.

One coordinator per enabled source; an analytics coordinator on top.

TODO: port from pollenwatch/.../coordinator.py ~AS-IS (domain-agnostic).
Adapt: runtime-data dataclass, source-instance wiring. Pattern unchanged.
"""
