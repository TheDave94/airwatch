"""Canonical AirWatch pollutant registry + band tables + band-authority provenance.

Single source of truth for the pollutants AirWatch tracks: display identity, HA
``device_class`` + unit, the air-quality index scales, and the WHO / EU health &
legal thresholds used as overlays. Which upstream sources can report each
pollutant lives here too.

This is the REBUILD analogue of PollenWatch's ``species_registry.py``. The
PollenWatch ``ThresholdStatus`` *evidence-provenance* concept is reused here as
:class:`BandAuthority` — a band's authority is **observable rather than asserted**
(OPEN_QUESTIONS.md Q4). We do not invent thresholds; every band cites its
**authority + value + averaging window**, and — for the WHO health bands — the
**systematic-review DOI** it rests on.

All numbers in this module are traced to the cited primary sources in the
repository's ``THRESHOLDS.md`` (the verified evidence base; that document is the
test oracle for ``tests/test_pollutant_registry.py``).

Kept import-free of ``homeassistant`` so the data layer is testable in isolation
— same discipline as ``sources/base.py`` and ``const.py``. The HA ``device_class``
is stored as a plain string; ``sensor.py`` maps it onto ``SensorDeviceClass``.

Provenance model (Q4 — expose, don't assert)
--------------------------------------------
Five *distinct* band authorities are carried, never collapsed into one verdict:

- **Classic EAQI** (:data:`EAQI_CLASSIC`) — the European Air Quality Index as
  implemented by **Open-Meteo/CAMS**, i.e. exactly what AirWatch's primary source
  returns in ``european_aqi``. PM on a 24-hour running mean, gases hourly. This is
  the operational display/colour scale and the basis for the cross-source
  consensus level (``level_for_value``). Source: Open-Meteo air-quality API docs.
- **Revised EEA index** (:data:`EAQI_REVISED`) — the EEA's **2024-revised**,
  WHO-aligned index bands (e.g. PM2.5 "Good" 0–5 rather than the classic 0–10),
  now the official EEA index. Carried as a distinct authority so a user can see
  which index a rating comes from. (The classic set is *not* wrong — it is what
  ``european_aqi`` numerically agrees with — but it is no longer the EEA's
  published index.) Source: airindex.eea.europa.eu; methodology ETC-HE 2024/17.
- **WHO 2021** (:data:`WHO_GUIDELINES`, authority ``who_2021``) — the 2021 Global
  Air Quality Guidelines: the AQG level **and** the interim targets (IT-1..IT-n)
  for **each** averaging window WHO defines per pollutant (annual / 24-h / 8-h /
  peak-season). Each entry cites the WHO-commissioned systematic-review DOI.
- **WHO retained** (authority ``who_retained``) — the short-averaging guidelines
  from the 2000/2005 editions that WHO 2021 explicitly states *remain valid* and
  were not re-evaluated (NO₂ 1-h 200; SO₂ 10-min 500; CO 8-h/1-h/15-min). These
  are the genuinely **hour-comparable** WHO numbers — they resolve the
  averaging-period mismatch with real WHO science rather than only a caveat.
- **EU 2024/2881** (authority ``eu_2024_2881``) — the in-force Ambient Air Quality
  Directive, with **both** statutory milestones (attain by 2026 ≈ the old values;
  attain by 2030 tightened toward WHO), each dated. The **repealed** 2008/50/EC
  values are retained under authority ``eu_2008_50_ec`` (history is part of
  provenance), tagged ``status="repealed"`` — never presented as active.

The **US EPA AQI** remains a reserved authority, not populated in v1.

Carbon monoxide note: WHO/EU express CO in **mg/m³**; AirWatch keeps CO in its
native **µg/m³** (Q3 — Open-Meteo reports µg/m³). All CO thresholds below are
therefore stored in µg/m³ (= the document mg/m³ value × 1000), with the original
mg/m³ recorded in each entry's ``note`` so the source value stays visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final


class PollutantKind(StrEnum):
    """How a pollutant's value is expressed."""

    #: A mass concentration in µg/m³ (PM, gases).
    CONCENTRATION = "concentration"
    #: A dimensionless aggregate index (european_aqi).
    INDEX = "index"


class BandAuthority(StrEnum):
    """Provenance of a band/threshold — *where the number comes from*.

    Reuses the spirit of PollenWatch's ``ThresholdStatus`` (issue #3): expose the
    authority of a band rather than assert a verdict. A consumer can see that a
    "Poor" classification rests on the classic EEA index while the WHO health
    overlay would call the same reading an exceedance.
    """

    #: Classic EEA European Air Quality Index, as implemented by Open-Meteo/CAMS.
    #: AirWatch's operational display + colour scale (what ``european_aqi`` is).
    EAQI_CLASSIC = "eaqi_classic"
    #: EEA's 2024-revised European AQI index (stricter; WHO-aligned). The current
    #: official EEA index. Carried as a distinct authority.
    EAQI_EEA_2024 = "eaqi_eea_2024"
    #: WHO 2021 global air quality guidelines (AQG + interim targets). Health overlay.
    WHO_2021 = "who_2021"
    #: WHO 2000/2005 short-averaging guidelines that WHO 2021 states remain valid
    #: (the hour-comparable values not re-evaluated in 2021).
    WHO_RETAINED = "who_retained"
    #: EU ambient-air limit/target values — Directive (EU) 2024/2881, in force.
    EU_2024_2881 = "eu_2024_2881"
    #: EU Directive 2008/50/EC — REPEALED by 2024/2881. Retained as prior provenance.
    EU_2008_50_EC = "eu_2008_50_ec"
    #: US EPA AQI / NAAQS breakpoints. RESERVED, not populated in v1 (needs gas
    #: unit conversion + the piecewise AQI computation; US-centric for an EU/CAMS
    #: integration). Kept here so the authority is nameable when implemented.
    US_EPA_AQI = "us_epa_aqi"


# --- EAQI band presentation -----------------------------------------------
#: 1-based EAQI band → (label, hex colour). Official EEA European Air Quality
#: Index palette (shared by the classic and revised index — same 6 band names).
#: Drives the card colour ramp (OPEN_QUESTIONS.md Q5).
EAQI_BANDS: Final[dict[int, tuple[str, str]]] = {
    1: ("good", "#50f0e6"),
    2: ("fair", "#50ccaa"),
    3: ("moderate", "#f0e641"),
    4: ("poor", "#ff5050"),
    5: ("very_poor", "#960032"),
    6: ("extremely_poor", "#7d2181"),
}


@dataclass(frozen=True)
class EaqiScale:
    """An air-quality index band scale with its authority + averaging basis.

    ``bounds`` maps a pollutant key to five ascending µg/m³ upper bounds; bands
    1–5 are ``value <= bound`` and anything above the last bound is band 6. The
    ``european_aqi`` index value has its own 20/40/60/80/100 scale (only the
    classic Open-Meteo index emits that numeric value).
    """

    authority: str
    bounds: dict[str, tuple[float, float, float, float, float]]
    averaging: dict[str, str]
    note: str


#: Classic EAQI — exactly what Open-Meteo/CAMS returns. VERIFIED against the
#: Open-Meteo air-quality API docs (THRESHOLDS.md §2a). PM = 24-hour running mean,
#: gases hourly. CO is NOT part of the EAQI.
EAQI_CLASSIC: Final = EaqiScale(
    authority=BandAuthority.EAQI_CLASSIC.value,
    bounds={
        "pm2_5": (10, 20, 25, 50, 75),
        "pm10": (20, 40, 50, 100, 150),
        "nitrogen_dioxide": (40, 90, 120, 230, 340),
        "ozone": (50, 100, 130, 240, 380),
        "sulphur_dioxide": (100, 200, 350, 500, 750),
    },
    averaging={
        "pm2_5": "24-hour",
        "pm10": "24-hour",
        "nitrogen_dioxide": "1-hour",
        "ozone": "1-hour",
        "sulphur_dioxide": "1-hour",
        "european_aqi": "aggregate",
    },
    note=(
        "Classic EEA / Open-Meteo breakpoints — what european_aqi numerically "
        "agrees with on the same fetch. Superseded as the EEA's published index "
        "by the 2024 revision (BandAuthority.EAQI_EEA_2024)."
    ),
)

#: Revised EEA index — the 2024, WHO-aligned official EEA index. VERIFIED from
#: airindex.eea.europa.eu (THRESHOLDS.md §2b). All pollutants hourly per the EEA
#: index page. Distinct from the classic set Open-Meteo returns.
EAQI_REVISED: Final = EaqiScale(
    authority=BandAuthority.EAQI_EEA_2024.value,
    bounds={
        "pm2_5": (5, 15, 50, 90, 140),
        "pm10": (15, 45, 120, 195, 270),
        "nitrogen_dioxide": (10, 25, 60, 100, 150),
        "ozone": (60, 100, 120, 160, 180),
        "sulphur_dioxide": (20, 40, 125, 190, 275),
    },
    averaging={
        "pm2_5": "1-hour",
        "pm10": "1-hour",
        "nitrogen_dioxide": "1-hour",
        "ozone": "1-hour",
        "sulphur_dioxide": "1-hour",
    },
    note=(
        "EEA 2024-revised index (WHO-aligned Good/Fair cut-points). The current "
        "official EEA index; methodology ETC-HE 2024/17. Open-Meteo's european_aqi "
        "value still follows the classic scale, so the two can disagree."
    ),
)

#: The european_aqi index value bands (0–20 good … >100 extremely poor).
_EAQI_INDEX_BOUNDS: Final[tuple[float, float, float, float, float]] = (
    20, 40, 60, 80, 100,
)


# --- systematic-review DOIs (WHO 2021 health-endpoint basis, THRESHOLDS §7) -
_DOI_CHEN_HOEK_2020 = "10.1016/j.envint.2020.105974"      # PM, long-term mortality
_DOI_HUANGFU_2020 = "10.1016/j.envint.2020.105998"        # NO2/O3, long-term mortality
_DOI_ORELLANO_2020 = "10.1016/j.envint.2020.105876"       # PM/NO2/O3, short-term mortality
_DOI_ORELLANO_2021 = "10.1016/j.envint.2021.106434"       # SO2, short-term mortality
_DOI_LEE_2020 = "10.1016/j.envint.2020.105901"            # CO, short-term (MI)


# --- WHO guideline overlay (2021 AQG + interim targets, + retained values) --
@dataclass(frozen=True)
class WhoGuideline:
    """A WHO guideline value for one averaging window.

    ``aqg`` is the guideline value in the pollutant's native unit (µg/m³; CO
    converted from mg/m³). ``interim_targets`` are IT-1..IT-n in descending order
    (loosest first, closest to the AQG last); empty for the retained 2000/2005
    values. ``basis`` carries the WHO-commissioned systematic-review DOI(s) for
    the 2021 guidelines (empty for retained values, which predate them).
    """

    averaging: str
    aqg: float
    authority: str
    interim_targets: tuple[float, ...] = ()
    basis: tuple[str, ...] = ()
    note: str | None = None


_W21 = BandAuthority.WHO_2021.value
_WRET = BandAuthority.WHO_RETAINED.value

#: WHO guidelines per pollutant — the FULL set (every averaging window WHO
#: defines + interim targets + retained short-averaging values). VERIFIED from
#: the WHO 2021 guidelines, Table 0.1 and Table 0.2 (THRESHOLDS.md §3).
WHO_GUIDELINES: Final[dict[str, tuple[WhoGuideline, ...]]] = {
    "pm2_5": (
        WhoGuideline("annual", 5, _W21, (35, 25, 15, 10), (_DOI_CHEN_HOEK_2020,)),
        WhoGuideline("24-hour", 15, _W21, (75, 50, 37.5, 25), (_DOI_ORELLANO_2020,)),
    ),
    "pm10": (
        WhoGuideline("annual", 15, _W21, (70, 50, 30, 20), (_DOI_CHEN_HOEK_2020,)),
        WhoGuideline("24-hour", 45, _W21, (150, 100, 75, 50), (_DOI_ORELLANO_2020,)),
    ),
    "nitrogen_dioxide": (
        WhoGuideline("annual", 10, _W21, (40, 30, 20), (_DOI_HUANGFU_2020,)),
        WhoGuideline("24-hour", 25, _W21, (120, 50), (_DOI_ORELLANO_2020,)),
        WhoGuideline(
            "1-hour", 200, _WRET,
            note="WHO 2000 1-hour guideline; remains valid (not re-evaluated 2021).",
        ),
    ),
    "ozone": (
        WhoGuideline("peak season", 60, _W21, (100, 70), (_DOI_HUANGFU_2020,)),
        WhoGuideline("8-hour", 100, _W21, (160, 120), (_DOI_ORELLANO_2020,)),
    ),
    "sulphur_dioxide": (
        WhoGuideline("24-hour", 40, _W21, (125, 50), (_DOI_ORELLANO_2021,)),
        WhoGuideline(
            "10-minute", 500, _WRET,
            note="WHO 2000 10-minute guideline; remains valid (not re-evaluated 2021).",
        ),
    ),
    "carbon_monoxide": (
        WhoGuideline(
            "24-hour", 4000, _W21, (7000,), (_DOI_LEE_2020,),
            note="WHO 2021 AQG 4 mg/m³ (IT-1 7 mg/m³); stored as µg/m³.",
        ),
        WhoGuideline(
            "8-hour", 10000, _WRET,
            note="WHO 2000 8-hour 10 mg/m³; remains valid. Stored as µg/m³.",
        ),
        WhoGuideline(
            "1-hour", 35000, _WRET,
            note="WHO 2000 1-hour 35 mg/m³; remains valid. Stored as µg/m³.",
        ),
        WhoGuideline(
            "15-minute", 100000, _WRET,
            note="WHO 2000 15-minute 100 mg/m³; remains valid. Stored as µg/m³.",
        ),
    ),
}


# --- EU ambient-air standards (2024/2881 in force; 2008/50/EC repealed) -----
@dataclass(frozen=True)
class EuStandard:
    """An EU ambient-air standard value, dated and authority-tagged (µg/m³).

    ``kind`` is "limit value" / "target value" / "long-term objective". ``attain_by``
    is the statutory attainment date (ISO, or a year). ``status`` is "in force" or
    "repealed". CO values are stored in µg/m³ (document mg/m³ × 1000).
    """

    averaging: str
    value: float
    kind: str
    attain_by: str
    authority: str
    status: str
    max_exceedances: str | None = None
    note: str | None = None


_EU24 = BandAuthority.EU_2024_2881.value
_EU08 = BandAuthority.EU_2008_50_EC.value
_INFORCE = "in force"
_REPEALED = "repealed"

#: EU standards per pollutant — Directive (EU) 2024/2881 Annex I, BOTH milestones
#: (Table 2 / attain by 2026-12-11; Table 1 / attain by 2030-01-01) plus ozone
#: target & long-term objective; and the REPEALED 2008/50/EC values as prior
#: provenance. VERIFIED from the OJ text and the EC standards page (THRESHOLDS §4).
EU_STANDARDS: Final[dict[str, tuple[EuStandard, ...]]] = {
    "pm2_5": (
        EuStandard("calendar year", 25, "limit value", "2026-12-11", _EU24, _INFORCE),
        EuStandard("24-hour", 25, "limit value", "2030-01-01", _EU24, _INFORCE,
                   "≤18 days/year"),
        EuStandard("calendar year", 10, "limit value", "2030-01-01", _EU24, _INFORCE),
        EuStandard("calendar year", 25, "limit value", "2015", _EU08, _REPEALED),
        EuStandard("calendar year", 20, "limit value", "2020", _EU08, _REPEALED,
                   note="2008/50/EC Stage-2 indicative limit."),
    ),
    "pm10": (
        EuStandard("24-hour", 50, "limit value", "2026-12-11", _EU24, _INFORCE,
                   "≤35 days/year"),
        EuStandard("calendar year", 40, "limit value", "2026-12-11", _EU24, _INFORCE),
        EuStandard("24-hour", 45, "limit value", "2030-01-01", _EU24, _INFORCE,
                   "≤18 days/year"),
        EuStandard("calendar year", 20, "limit value", "2030-01-01", _EU24, _INFORCE),
        EuStandard("24-hour", 50, "limit value", "2005", _EU08, _REPEALED,
                   "≤35 days/year"),
        EuStandard("calendar year", 40, "limit value", "2005", _EU08, _REPEALED),
    ),
    "nitrogen_dioxide": (
        EuStandard("1-hour", 200, "limit value", "2026-12-11", _EU24, _INFORCE,
                   "≤18 hours/year"),
        EuStandard("calendar year", 40, "limit value", "2026-12-11", _EU24, _INFORCE),
        EuStandard("1-hour", 200, "limit value", "2030-01-01", _EU24, _INFORCE,
                   "≤3 times/year"),
        EuStandard("24-hour", 50, "limit value", "2030-01-01", _EU24, _INFORCE,
                   "≤18 days/year"),
        EuStandard("calendar year", 20, "limit value", "2030-01-01", _EU24, _INFORCE),
        EuStandard("1-hour", 200, "limit value", "2010", _EU08, _REPEALED,
                   "≤18 hours/year"),
        EuStandard("calendar year", 40, "limit value", "2010", _EU08, _REPEALED),
    ),
    "ozone": (
        EuStandard("max daily 8-hour mean", 120, "target value", "2030-01-01",
                   _EU24, _INFORCE,
                   "≤18 days/year (3-yr avg); ≤25 days/year until 2030"),
        EuStandard("max daily 8-hour mean", 100, "long-term objective", "2050-01-01",
                   _EU24, _INFORCE, "≤3 days/year (99th percentile)"),
        EuStandard("max daily 8-hour mean", 120, "target value", "2010", _EU08,
                   _REPEALED, "≤25 days/year (3-yr avg)"),
    ),
    "sulphur_dioxide": (
        EuStandard("1-hour", 350, "limit value", "2026-12-11", _EU24, _INFORCE,
                   "≤24 hours/year"),
        EuStandard("24-hour", 125, "limit value", "2026-12-11", _EU24, _INFORCE,
                   "≤3 days/year"),
        EuStandard("1-hour", 350, "limit value", "2030-01-01", _EU24, _INFORCE,
                   "≤3 times/year"),
        EuStandard("24-hour", 50, "limit value", "2030-01-01", _EU24, _INFORCE,
                   "≤18 days/year"),
        EuStandard("calendar year", 20, "limit value", "2030-01-01", _EU24, _INFORCE),
        EuStandard("1-hour", 350, "limit value", "2005", _EU08, _REPEALED,
                   "≤24 hours/year"),
        EuStandard("24-hour", 125, "limit value", "2005", _EU08, _REPEALED,
                   "≤3 days/year"),
    ),
    "carbon_monoxide": (
        EuStandard("max daily 8-hour mean", 10000, "limit value", "2026-12-11",
                   _EU24, _INFORCE, note="10 mg/m³; stored as µg/m³."),
        EuStandard("max daily 8-hour mean", 10000, "limit value", "2030-01-01",
                   _EU24, _INFORCE, note="10 mg/m³; stored as µg/m³."),
        EuStandard("24-hour", 4000, "limit value", "2030-01-01", _EU24, _INFORCE,
                   "≤18 days/year", "4 mg/m³ (new daily limit); stored as µg/m³."),
        EuStandard("max daily 8-hour mean", 10000, "limit value", "2005", _EU08,
                   _REPEALED, note="10 mg/m³; stored as µg/m³."),
    ),
}


@dataclass(frozen=True)
class PollutantInfo:
    """Canonical metadata for an AirWatch pollutant.

    ``device_class`` is the HA sensor device_class string, or ``None`` to omit it.
    CO omits the device_class deliberately: HA's ``carbon_monoxide`` class accepts
    ppm only, and AirWatch keeps the source's native µg/m³ rather than baking in a
    temperature/pressure conversion (OPEN_QUESTIONS.md Q3). The other concentration
    pollutants' device_class accepts µg/m³ natively.

    ``sources`` is the *global* set — the upstream sources that can report this
    pollutant when configured and in coverage. Per-install coverage is computed at
    runtime by intersecting with the user's enabled sources.
    """

    key: str
    name: str
    formula: str
    kind: PollutantKind
    device_class: str | None
    unit: str | None
    sources: frozenset[str]


# Source keys — literal strings mirrored from const.SOURCE_*. Inline to keep this
# module import-free of const (const derives POLLUTANT_NAMES from here).
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
def _band_index_for_bounds(
    bounds: tuple[float, ...] | None, value: float | None
) -> int | None:
    """Generic 6-band lookup: bands 1–5 by ``value <= bound``, else band 6."""
    if value is None or bounds is None:
        return None
    for band, upper in enumerate(bounds, start=1):
        if value <= upper:
            return band
    return 6


def eaqi_band_for(pollutant: str, value: float | None) -> int | None:
    """Classic EAQI band (1–6) for a reading — Open-Meteo breakpoints.

    For ``european_aqi`` the index value itself is banded (0–20 good …). For a
    concentration pollutant its µg/m³ value is banded by the classic bounds.
    Returns ``None`` for CO (not in the EAQI) or an unknown/missing value. This is
    the operational scale (consensus + ``european_aqi`` agreement) — use
    :func:`index_band_for` for the revised index.
    """
    if pollutant == "european_aqi":
        return _band_index_for_bounds(_EAQI_INDEX_BOUNDS, value)
    return _band_index_for_bounds(EAQI_CLASSIC.bounds.get(pollutant), value)


def index_band_for(scale: EaqiScale, pollutant: str, value: float | None) -> int | None:
    """Band (1–6) for a reading on a given index scale (classic or revised)."""
    return _band_index_for_bounds(scale.bounds.get(pollutant), value)


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

    EAQI-banded pollutants collapse their 6 classic bands → 3 levels. CO (no EAQI
    band) uses WHO 24h / EU 8h-limit bounds. Returns ``None`` for a missing value.
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


# --- accessors ------------------------------------------------------------
def who_guidelines_for(pollutant: str) -> tuple[WhoGuideline, ...]:
    """All WHO guideline windows (2021 + retained) for a pollutant."""
    return WHO_GUIDELINES.get(pollutant, ())


def eu_standards_for(pollutant: str) -> tuple[EuStandard, ...]:
    """All EU standards (2024/2881 in-force + 2008/50/EC repealed) for a pollutant."""
    return EU_STANDARDS.get(pollutant, ())


def _index_entry(scale: EaqiScale, pollutant: str, band: int | None) -> dict | None:
    """Provenance entry for one index scale given a precomputed band, or ``None``."""
    if band is None:
        return None
    return {
        "authority": scale.authority,
        "band": eaqi_band_label(band),
        "band_index": band,
        "colour": eaqi_band_colour(band),
        "averaging": scale.averaging.get(pollutant),
        "note": scale.note,
    }


def _who_entry(g: WhoGuideline, value: float) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "authority": g.authority,
        "value": g.aqg,
        "averaging": g.averaging,
        "exceeds": value >= g.aqg,
    }
    if g.interim_targets:
        entry["interim_targets"] = list(g.interim_targets)
    if g.basis:
        entry["basis"] = list(g.basis)
    if g.note:
        entry["note"] = g.note
    return entry


def _eu_entry(s: EuStandard, value: float) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "authority": s.authority,
        "value": s.value,
        "averaging": s.averaging,
        "kind": s.kind,
        "attain_by": s.attain_by,
        "status": s.status,
        "exceeds": value >= s.value,
    }
    if s.max_exceedances:
        entry["max_exceedances"] = s.max_exceedances
    if s.note:
        entry["note"] = s.note
    return entry


def band_provenance(pollutant: str, value: float | None) -> dict[str, Any]:
    """Provenance-tagged band assessments for a reading — authorities DISTINCT.

    Returns a dict keyed by authority, each entry carrying its provenance and
    **never** collapsed into a single verdict (OPEN_QUESTIONS.md Q4):

    - ``eaqi_classic`` / ``eaqi_eea_2024`` — single dict each (band + averaging +
      colour). ``european_aqi`` carries only the classic index band; CO carries
      neither (not part of the EAQI).
    - ``who_2021`` / ``who_retained`` — **lists**, one entry per averaging window
      (annual / 24-h / 8-h / peak-season / hour-comparable retained values), each
      with value + averaging + exceeds (+ interim targets + systematic-review DOI
      for the 2021 entries).
    - ``eu_2024_2881`` / ``eu_2008_50_ec`` — **lists**, one entry per limit value
      across both statutory milestones; the 2008 entries are tagged
      ``status="repealed"`` (history, not an active assessment).

    Every value compared here is an hourly reading; each entry's ``averaging``
    field exposes its native window so the mismatch is visible. The retained WHO
    short-averaging entries (NO₂ 1-h, CO 1-h/8-h, SO₂ 10-min) are the genuinely
    hour-comparable WHO numbers. Authorities/entries that don't apply are omitted;
    a ``None`` value yields ``{}``.
    """
    out: dict[str, Any] = {}
    if value is None:
        return out

    # Classic uses eaqi_band_for so the european_aqi index value (0–100 scale) is
    # handled alongside the concentration breakpoints.
    classic = _index_entry(EAQI_CLASSIC, pollutant, eaqi_band_for(pollutant, value))
    if classic is not None:
        out[BandAuthority.EAQI_CLASSIC.value] = classic
    # The revised index has no european_aqi index-value scale.
    if pollutant != "european_aqi":
        revised = _index_entry(
            EAQI_REVISED, pollutant, index_band_for(EAQI_REVISED, pollutant, value)
        )
        if revised is not None:
            out[BandAuthority.EAQI_EEA_2024.value] = revised

    who_2021: list[dict[str, Any]] = []
    who_retained: list[dict[str, Any]] = []
    for g in WHO_GUIDELINES.get(pollutant, ()):
        (who_2021 if g.authority == _W21 else who_retained).append(
            _who_entry(g, value)
        )
    if who_2021:
        out[BandAuthority.WHO_2021.value] = who_2021
    if who_retained:
        out[BandAuthority.WHO_RETAINED.value] = who_retained

    eu_current: list[dict[str, Any]] = []
    eu_repealed: list[dict[str, Any]] = []
    for s in EU_STANDARDS.get(pollutant, ()):
        (eu_current if s.authority == _EU24 else eu_repealed).append(
            _eu_entry(s, value)
        )
    if eu_current:
        out[BandAuthority.EU_2024_2881.value] = eu_current
    if eu_repealed:
        out[BandAuthority.EU_2008_50_EC.value] = eu_repealed

    return out
