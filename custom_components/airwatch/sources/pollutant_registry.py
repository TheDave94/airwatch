"""Canonical AirWatch pollutant registry + band tables + band-authority provenance.

Single source of truth for the pollutants AirWatch tracks: display identity, HA
``device_class`` + unit, the European Air Quality Index (EAQI) breakpoints used
for the display/colour scale, and the WHO 2021 guideline used as the health
overlay. Which upstream sources can report each pollutant lives here too.

This is the REBUILD analogue of PollenWatch's ``species_registry.py``. The
PollenWatch ``ThresholdStatus`` *evidence-provenance* concept is reused here as
:class:`BandAuthority` — a band's authority is **observable rather than
asserted** (OPEN_QUESTIONS.md Q4). We do not invent thresholds; every band cites
its authority, value, and averaging window.

Kept import-free of ``homeassistant`` so the data layer is testable in isolation
— same discipline as ``sources/base.py`` and ``const.py``. The HA ``device_class``
is stored as a plain string; ``sensor.py`` maps it onto ``SensorDeviceClass``.

Provenance notes
----------------
- **EAQI breakpoints** below are the *classic EEA European Air Quality Index*
  values **as implemented by Open-Meteo/CAMS** (which is what AirWatch's primary
  source returns in ``european_aqi``). The EEA **revised** these breakpoints in
  2023 (stricter, closer to WHO — e.g. PM2.5 "Good" 0–5 rather than 0–10); that
  revision is recorded as :attr:`BandAuthority.EEA_2023` and surfaced as an
  alternate so the divergence is visible, not hidden. We use the classic set so
  a pollutant's derived band agrees with the ``european_aqi`` value on the same
  fetch.  Source: open-meteo.com air-quality API docs; EEA AQI definition.
- **WHO 2021** = the WHO global air quality guidelines (AQG), 2021
  (ISBN 978-92-4-003422-8). These are 24-hour / annual / 8-hour means; AirWatch
  readings are hourly, so the averaging-period mismatch is carried on each band
  and surfaced as the ``band_averaging_period`` attribute — a provenance caveat,
  not a silent comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class PollutantKind(StrEnum):
    """How a pollutant's value is expressed."""

    #: A mass concentration in µg/m³ (PM, gases).
    CONCENTRATION = "concentration"
    #: A dimensionless aggregate index (european_aqi).
    INDEX = "index"


class BandAuthority(StrEnum):
    """Provenance of a band/threshold — *where the number comes from*.

    Reuses the spirit of PollenWatch's ``ThresholdStatus`` (issue #3): expose
    the authority of a band rather than assert a verdict. A consumer can see
    that a "Poor" classification rests on the classic EEA index while the WHO
    health overlay would call the same reading an exceedance.
    """

    #: Classic EEA European Air Quality Index, as implemented by Open-Meteo/CAMS.
    #: AirWatch's operational display + colour scale.
    EAQI = "eaqi_classic"
    #: EEA's 2023-revised European AQI breakpoints (stricter; WHO-aligned).
    #: Carried as an alternate so the revision is observable.
    EEA_2023 = "eea_2023"
    #: WHO 2021 global air quality guidelines (health-strict). The health overlay.
    WHO_2021 = "who_2021"
    #: EU ambient-air legal limit values (2008/50/EC + the 2024 revision).
    EU_LIMIT = "eu_limit"
    #: US EPA AQI / NAAQS breakpoints (familiar ramp). Documented alternate.
    US_EPA_AQI = "us_epa_aqi"


# --- EAQI band presentation (classic EEA palette) -------------------------
#: 1-based EAQI band → (label, hex colour). Official EEA European Air Quality
#: Index palette. Drives the card colour ramp (OPEN_QUESTIONS.md Q5).
EAQI_BANDS: Final[dict[int, tuple[str, str]]] = {
    1: ("good", "#50f0e6"),
    2: ("fair", "#50ccaa"),
    3: ("moderate", "#f0e641"),
    4: ("poor", "#ff5050"),
    5: ("very_poor", "#960032"),
    6: ("extremely_poor", "#7d2181"),
}

#: Per-pollutant EAQI upper bounds (µg/m³), classic EEA / Open-Meteo set. Five
#: ascending bounds define the first five bands; a value above the last bound is
#: band 6 (extremely poor). ``european_aqi`` (the index value) is banded on its
#: own 20/40/60/80/100 scale instead — see ``_EAQI_INDEX_BOUNDS``.
_EAQI_BOUNDS: Final[dict[str, tuple[float, float, float, float, float]]] = {
    "pm2_5": (10, 20, 25, 50, 75),
    "pm10": (20, 40, 50, 100, 150),
    "nitrogen_dioxide": (40, 90, 120, 230, 340),
    "ozone": (50, 100, 130, 240, 380),
    "sulphur_dioxide": (100, 200, 350, 500, 750),
    # carbon_monoxide: NOT part of the EAQI — banded via WHO/EU only.
}
#: The european_aqi index value bands (0–20 good … >100 extremely poor).
_EAQI_INDEX_BOUNDS: Final[tuple[float, float, float, float, float]] = (
    20, 40, 60, 80, 100,
)


# --- WHO 2021 guideline overlay -------------------------------------------
@dataclass(frozen=True)
class WhoGuideline:
    """A WHO 2021 air-quality guideline value and its averaging period.

    ``value`` is in the pollutant's native unit (µg/m³ for all of these,
    including CO — WHO expresses CO as a mass concentration). ``averaging`` is
    the WHO averaging window the value applies to; AirWatch readings are hourly,
    so comparing them is an approximation surfaced as a provenance caveat.
    """

    value: float
    averaging: str  # e.g. "24-hour", "annual", "8-hour"


#: WHO 2021 AQG levels. CO 24-hour = 4 mg/m³ = 4000 µg/m³.
_WHO_2021: Final[dict[str, WhoGuideline]] = {
    "pm2_5": WhoGuideline(15, "24-hour"),
    "pm10": WhoGuideline(45, "24-hour"),
    "nitrogen_dioxide": WhoGuideline(25, "24-hour"),
    "ozone": WhoGuideline(100, "8-hour"),
    "sulphur_dioxide": WhoGuideline(40, "24-hour"),
    "carbon_monoxide": WhoGuideline(4000, "24-hour"),
}


@dataclass(frozen=True)
class PollutantInfo:
    """Canonical metadata for an AirWatch pollutant.

    ``device_class`` is the HA sensor device_class string, or ``None`` to omit
    it. CO omits the device_class deliberately: HA's ``carbon_monoxide`` class
    accepts ppm only, and AirWatch keeps the source's native µg/m³ rather than
    baking in a temperature/pressure conversion (OPEN_QUESTIONS.md Q3). The
    other concentration pollutants' device_class accepts µg/m³ natively.

    ``sources`` is the *global* set — the upstream sources that can report this
    pollutant when configured and in coverage. Per-install coverage is computed
    at runtime by intersecting with the user's enabled sources.
    """

    key: str
    name: str
    formula: str
    kind: PollutantKind
    device_class: str | None
    unit: str | None
    sources: frozenset[str]


# Source keys — literal strings mirrored from const.SOURCE_*. Inline to keep
# this module import-free of const (const derives POLLUTANT_NAMES from here).
_OM = "open_meteo"
_SC = "sensor_community"
_LS = "land_steiermark"

#: µg/m³ for the mass-concentration pollutants. CO too (Q3): native µg/m³.
_UGM3 = "µg/m³"


CANONICAL_POLLUTANTS: Final[dict[str, PollutantInfo]] = {
    "pm2_5": PollutantInfo(
        "pm2_5", "PM2.5", "PM₂.₅", PollutantKind.CONCENTRATION,
        "pm25", _UGM3, frozenset({_OM, _SC, _LS}),
    ),
    "pm10": PollutantInfo(
        "pm10", "PM10", "PM₁₀", PollutantKind.CONCENTRATION,
        "pm10", _UGM3, frozenset({_OM, _SC, _LS}),
    ),
    "nitrogen_dioxide": PollutantInfo(
        "nitrogen_dioxide", "Nitrogen dioxide", "NO₂", PollutantKind.CONCENTRATION,
        "nitrogen_dioxide", _UGM3, frozenset({_OM, _LS}),
    ),
    "ozone": PollutantInfo(
        "ozone", "Ozone", "O₃", PollutantKind.CONCENTRATION,
        "ozone", _UGM3, frozenset({_OM, _LS}),
    ),
    "sulphur_dioxide": PollutantInfo(
        "sulphur_dioxide", "Sulphur dioxide", "SO₂", PollutantKind.CONCENTRATION,
        "sulphur_dioxide", _UGM3, frozenset({_OM, _LS}),
    ),
    # CO: device_class omitted (Q3). Native µg/m³; ppm exposed as a tagged
    # attribute by sensor.py.
    "carbon_monoxide": PollutantInfo(
        "carbon_monoxide", "Carbon monoxide", "CO", PollutantKind.CONCENTRATION,
        None, _UGM3, frozenset({_OM, _LS}),
    ),
    # European AQI: dimensionless aggregate index. Only Open-Meteo provides it.
    "european_aqi": PollutantInfo(
        "european_aqi", "European AQI", "EAQI", PollutantKind.INDEX,
        "aqi", None, frozenset({_OM}),
    ),
}

ALL_POLLUTANT_KEYS: Final[frozenset[str]] = frozenset(CANONICAL_POLLUTANTS.keys())


# --- CO ppm conversion (Q3: convenience attribute, NOT the state) ---------
#: Molar volume of an ideal gas at EU reference conditions (20 °C, 101.3 kPa),
#: in L/mol. US EPA uses 24.45 (25 °C); EU/WHO mass concentrations use 20 °C.
_MOLAR_VOLUME_20C: Final = 24.04
#: CO molar mass, g/mol.
_CO_MOLAR_MASS: Final = 28.01
CO_PPM_NOTE: Final = (
    "Converted from µg/m³ assuming 20 °C / 101.3 kPa "
    "(molar volume 24.04 L·mol⁻¹, CO molar mass 28.01 g·mol⁻¹). "
    "Open-Meteo reports CO in µg/m³; ppm is a convenience value only."
)


def co_ugm3_to_ppm(ugm3: float | None) -> float | None:
    """Convert a CO µg/m³ reading to ppm at EU reference conditions.

    ppm = µg/m³ × molar_volume / molar_mass / 1000. ``None`` in → ``None`` out.
    Exposed as the ``value_ppm`` attribute (Q3), never as the sensor state.
    """
    if ugm3 is None:
        return None
    return round(ugm3 * _MOLAR_VOLUME_20C / _CO_MOLAR_MASS / 1000.0, 4)


# --- banding helpers ------------------------------------------------------
def eaqi_band_for(pollutant: str, value: float | None) -> int | None:
    """EAQI band (1–6) for a reading, classic EEA / Open-Meteo breakpoints.

    For ``european_aqi`` the index value itself is banded (0–20 good …). For a
    concentration pollutant its µg/m³ value is banded by ``_EAQI_BOUNDS``.
    Returns ``None`` for CO (not in the EAQI) or an unknown/missing value.
    """
    if value is None:
        return None
    if pollutant == "european_aqi":
        bounds = _EAQI_INDEX_BOUNDS
    else:
        bounds = _EAQI_BOUNDS.get(pollutant)
        if bounds is None:
            return None
    for band, upper in enumerate(bounds, start=1):
        if value <= upper:
            return band
    return 6


def eaqi_band_label(band: int | None) -> str | None:
    """Label for an EAQI band (1–6). ``None`` in → ``None`` out."""
    if band is None:
        return None
    entry = EAQI_BANDS.get(band)
    return entry[0] if entry else None


def eaqi_band_colour(band: int | None) -> str | None:
    """Hex colour for an EAQI band (1–6). ``None`` in → ``None`` out."""
    if band is None:
        return None
    entry = EAQI_BANDS.get(band)
    return entry[1] if entry else None


# EAQI 6-band → common 3-level consensus scale (operational alignment, mirrors
# PollenWatch's index collapse). Good/Fair → 0 (none); Moderate/Poor → 1
# (elevated); Very poor/Extremely poor → 2 (high). The health-conservative
# take-the-higher bias lives once in analytics.consensus, not here.
_EAQI_BAND_TO_LEVEL: Final[dict[int, int]] = {1: 0, 2: 0, 3: 1, 4: 1, 5: 2, 6: 2}

# CO has no EAQI band; bucket it on WHO 24h (4000) + EU 8h legal limit (10000).
_CO_LEVEL_BOUNDS: Final[tuple[float, float]] = (4000.0, 10000.0)


def level_for_value(pollutant: str, value: float | None) -> int | None:
    """Bucket a reading to the common 0/1/2 level for cross-source consensus.

    EAQI-banded pollutants collapse their 6 bands → 3 levels. CO (no EAQI band)
    uses WHO 24h / EU 8h-limit bounds. Returns ``None`` for a missing value.
    """
    if value is None:
        return None
    if pollutant == "carbon_monoxide":
        onset, peak = _CO_LEVEL_BOUNDS
        if value >= peak:
            return 2
        if value >= onset:
            return 1
        return 0
    band = eaqi_band_for(pollutant, value)
    if band is None:
        return None
    return _EAQI_BAND_TO_LEVEL[band]


@dataclass(frozen=True)
class WhoAssessment:
    """Health overlay: does a reading exceed the WHO 2021 guideline?

    ``averaging`` is the WHO averaging window the guideline applies to;
    AirWatch readings are hourly, so ``exceeds`` is an approximate comparison
    surfaced with its provenance caveat, not asserted as a verdict.
    """

    guideline: float
    averaging: str
    exceeds: bool
    authority: str = BandAuthority.WHO_2021.value


def who_assessment_for(pollutant: str, value: float | None) -> WhoAssessment | None:
    """WHO 2021 exceedance overlay for a reading. ``None`` if no guideline."""
    guideline = _WHO_2021.get(pollutant)
    if guideline is None or value is None:
        return None
    return WhoAssessment(
        guideline=guideline.value,
        averaging=guideline.averaging,
        exceeds=value >= guideline.value,
    )


def who_guideline_for(pollutant: str) -> WhoGuideline | None:
    """The WHO 2021 guideline for a pollutant, or ``None``."""
    return _WHO_2021.get(pollutant)
