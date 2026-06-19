"""Unit tests for the pure pollutant registry (HA-free).

THRESHOLDS.md is the oracle: the WHO 2021 (Table 0.1 + retained Table 0.2), EU
(Directive (EU) 2024/2881 Annex I, both milestones; repealed 2008/50/EC), and the
classic + revised EAQI band values are locked here against the verified evidence
base. Also exercises the band helpers, the EAQI→3-level consensus collapse, and
the CO ppm conversion.
"""

from __future__ import annotations

import pytest

from custom_components.airwatch.sources.pollutant_registry import (
    EAQI_CLASSIC,
    EAQI_REVISED,
    BandAuthority,
    band_provenance,
    co_ugm3_to_ppm,
    eaqi_band_colour,
    eaqi_band_for,
    eaqi_band_label,
    eu_standards_for,
    index_band_for,
    level_for_value,
    who_guidelines_for,
)

# === EAQI banding ==========================================================
# Classic pm2_5 bounds: (10, 20, 25, 50, 75) -> bands 1..5 by <=, else 6.


@pytest.mark.parametrize(
    ("value", "band"),
    [
        (0, 1), (10, 1), (10.01, 2), (20, 2), (20.01, 3), (25, 3),
        (25.01, 4), (50, 4), (50.01, 5), (75, 5), (75.01, 6), (500, 6),
    ],
)
def test_eaqi_band_for_pm2_5_classic_boundaries(value, band):
    assert eaqi_band_for("pm2_5", value) == band


def test_eaqi_classic_bounds_match_open_meteo():
    """Lock classic bounds (THRESHOLDS §2a, Open-Meteo docs)."""
    assert EAQI_CLASSIC.bounds == {
        "pm2_5": (10, 20, 25, 50, 75),
        "pm10": (20, 40, 50, 100, 150),
        "nitrogen_dioxide": (40, 90, 120, 230, 340),
        "ozone": (50, 100, 130, 240, 380),
        "sulphur_dioxide": (100, 200, 350, 500, 750),
    }
    assert EAQI_CLASSIC.averaging["pm2_5"] == "24-hour"
    assert EAQI_CLASSIC.averaging["nitrogen_dioxide"] == "1-hour"


def test_eaqi_revised_bounds_match_eea_2024():
    """Lock the revised official EEA index bounds (THRESHOLDS §2b, airindex)."""
    assert EAQI_REVISED.bounds == {
        "pm2_5": (5, 15, 50, 90, 140),
        "pm10": (15, 45, 120, 195, 270),
        "nitrogen_dioxide": (10, 25, 60, 100, 150),
        "ozone": (60, 100, 120, 160, 180),
        "sulphur_dioxide": (20, 40, 125, 190, 275),
    }
    assert EAQI_REVISED.authority == BandAuthority.EAQI_EEA_2024.value
    # All pollutants hourly in the revised index.
    assert set(EAQI_REVISED.averaging.values()) == {"1-hour"}


@pytest.mark.parametrize(
    ("value", "band"),
    [(0, 1), (5, 1), (5.01, 2), (15, 2), (15.01, 3), (50, 3), (90, 4), (140, 5), (141, 6)],
)
def test_index_band_for_revised_pm2_5(value, band):
    assert index_band_for(EAQI_REVISED, "pm2_5", value) == band


def test_classic_and_revised_can_disagree():
    # pm2_5 = 8: classic "good" (<=10) but revised "fair" (6-15) — divergence visible.
    assert eaqi_band_label(eaqi_band_for("pm2_5", 8)) == "good"
    assert eaqi_band_label(index_band_for(EAQI_REVISED, "pm2_5", 8)) == "fair"


def test_eaqi_band_for_european_aqi_index_bounds():
    assert eaqi_band_for("european_aqi", 0) == 1
    assert eaqi_band_for("european_aqi", 20) == 1
    assert eaqi_band_for("european_aqi", 20.5) == 2
    assert eaqi_band_for("european_aqi", 100) == 5
    assert eaqi_band_for("european_aqi", 101) == 6


def test_eaqi_band_for_none_and_co_and_unknown_return_none():
    assert eaqi_band_for("pm2_5", None) is None
    assert eaqi_band_for("carbon_monoxide", 5000) is None  # CO not in EAQI
    assert eaqi_band_for("not_a_pollutant", 10) is None


def test_eaqi_band_label_and_colour():
    assert eaqi_band_label(1) == "good"
    assert eaqi_band_label(6) == "extremely_poor"
    assert eaqi_band_label(None) is None
    assert eaqi_band_label(7) is None
    assert eaqi_band_colour(1) == "#50f0e6"
    assert eaqi_band_colour(6) == "#7d2181"
    assert eaqi_band_colour(0) is None


# === level_for_value (EAQI 6-band -> 3-level collapse) =====================


# Severity now follows the REVISED EEA index pm2_5 bounds (5,15,50,90,140):
# bands {1,2}->0, {3,4}->1, {5,6}->2.
@pytest.mark.parametrize(
    ("value", "level"),
    [(5, 0), (15, 0), (16, 1), (50, 1), (90, 1), (91, 2), (150, 2)],
)
def test_level_for_value_pm2_5_collapse_revised(value, level):
    assert level_for_value("pm2_5", value) == level


def test_severity_uses_revised_eea_not_classic():
    """Behavior change lock: severity follows the revised WHO-aligned EEA index.

    Same values, classic vs revised collapse:
    - pm2_5 = 90: classic band 6 (extremely poor) -> level 2; revised band 4
      (poor) -> level 1.
    - pm2_5 = 18: classic band 2 (fair) -> level 0; revised band 3 (moderate)
      -> level 1 (stricter at the low end).
    """
    assert level_for_value("pm2_5", 90) == 1
    assert level_for_value("pm2_5", 18) == 1
    # The divergence value pm2_5 = 8: revised band is "fair" (collapses to 0).
    assert eaqi_band_label(index_band_for(EAQI_REVISED, "pm2_5", 8)) == "fair"
    assert level_for_value("pm2_5", 8) == 0


def test_level_for_value_none_and_unknown():
    assert level_for_value("pm2_5", None) is None
    assert level_for_value("not_a_pollutant", 10) is None


@pytest.mark.parametrize(
    ("value", "level"),
    [(0, 0), (3999, 0), (4000, 1), (9999, 1), (10000, 2), (50000, 2)],
)
def test_level_for_value_carbon_monoxide_bounds(value, level):
    assert level_for_value("carbon_monoxide", value) == level


# === WHO 2021 — full set locked against THRESHOLDS.md Table 0.1 / 0.2 ======
# (averaging, aqg, interim_targets, authority) per pollutant, in module order.

_W21 = BandAuthority.WHO_2021.value
_WRET = BandAuthority.WHO_RETAINED.value

EXPECTED_WHO = {
    "pm2_5": [
        ("annual", 5, (35, 25, 15, 10), _W21),
        ("24-hour", 15, (75, 50, 37.5, 25), _W21),
    ],
    "pm10": [
        ("annual", 15, (70, 50, 30, 20), _W21),
        ("24-hour", 45, (150, 100, 75, 50), _W21),
    ],
    "nitrogen_dioxide": [
        ("annual", 10, (40, 30, 20), _W21),
        ("24-hour", 25, (120, 50), _W21),
        ("1-hour", 200, (), _WRET),
    ],
    "ozone": [
        ("peak season", 60, (100, 70), _W21),
        ("8-hour", 100, (160, 120), _W21),
    ],
    "sulphur_dioxide": [
        ("24-hour", 40, (125, 50), _W21),
        ("10-minute", 500, (), _WRET),
    ],
    "carbon_monoxide": [
        ("24-hour", 4000, (7000,), _W21),
        ("8-hour", 10000, (), _WRET),
        ("1-hour", 35000, (), _WRET),
        ("15-minute", 100000, (), _WRET),
    ],
}


@pytest.mark.parametrize("pollutant", list(EXPECTED_WHO))
def test_who_guidelines_full_set_matches_thresholds_doc(pollutant):
    got = [
        (g.averaging, g.aqg, g.interim_targets, g.authority)
        for g in who_guidelines_for(pollutant)
    ]
    assert got == EXPECTED_WHO[pollutant]


def test_who_2021_entries_cite_a_systematic_review_doi():
    # Every WHO_2021 guideline carries a DOI; retained values carry none.
    for pollutant in EXPECTED_WHO:
        for g in who_guidelines_for(pollutant):
            if g.authority == _W21:
                assert g.basis and all("10.1016/j.envint" in d for d in g.basis)
            else:
                assert g.basis == ()


def test_who_no_guideline_for_index():
    assert who_guidelines_for("european_aqi") == ()


# === EU standards — both milestones + repealed, locked to THRESHOLDS §4 =====


def _eu(pollutant):
    return [
        (s.averaging, s.value, s.kind, s.attain_by, s.authority, s.status)
        for s in eu_standards_for(pollutant)
    ]


def test_eu_pm2_5_both_milestones_and_repealed():
    assert _eu("pm2_5") == [
        ("calendar year", 25, "limit value", "2026-12-11", "eu_2024_2881", "in force"),
        ("24-hour", 25, "limit value", "2030-01-01", "eu_2024_2881", "in force"),
        ("calendar year", 10, "limit value", "2030-01-01", "eu_2024_2881", "in force"),
        ("calendar year", 25, "limit value", "2015", "eu_2008_50_ec", "repealed"),
        ("calendar year", 20, "limit value", "2020", "eu_2008_50_ec", "repealed"),
    ]


def test_eu_no2_2030_tightening_and_exceedance_drop():
    no2 = eu_standards_for("nitrogen_dioxide")
    # 2030: annual 20; 1-hour 200 with ≤3 times/year (down from ≤18).
    annual_2030 = next(
        s for s in no2 if s.attain_by == "2030-01-01" and s.averaging == "calendar year"
    )
    assert annual_2030.value == 20
    hour_2030 = next(
        s for s in no2 if s.attain_by == "2030-01-01" and s.averaging == "1-hour"
    )
    assert hour_2030.max_exceedances == "≤3 times/year"
    # repealed 2008 annual was 40.
    annual_old = next(s for s in no2 if s.authority == "eu_2008_50_ec"
                      and s.averaging == "calendar year")
    assert annual_old.value == 40


def test_eu_co_new_daily_limit_and_units():
    co = eu_standards_for("carbon_monoxide")
    daily_2030 = next(s for s in co if s.averaging == "24-hour")
    assert daily_2030.value == 4000  # 4 mg/m³ stored as µg/m³
    assert daily_2030.attain_by == "2030-01-01"
    eight_hour = next(s for s in co if s.averaging == "max daily 8-hour mean"
                      and s.authority == "eu_2024_2881")
    assert eight_hour.value == 10000  # 10 mg/m³


def test_eu_ozone_target_and_long_term():
    o3 = eu_standards_for("ozone")
    target = next(s for s in o3 if s.kind == "target value" and s.authority == "eu_2024_2881")
    assert target.value == 120 and target.averaging == "max daily 8-hour mean"
    lto = next(s for s in o3 if s.kind == "long-term objective")
    assert lto.value == 100 and lto.attain_by == "2050-01-01"


def test_eu_no_standard_for_index():
    assert eu_standards_for("european_aqi") == ()


# === band_provenance — authorities distinct, never collapsed ===============


def test_band_provenance_pm2_5_carries_all_applicable_authorities():
    prov = band_provenance("pm2_5", 30)
    assert set(prov) == {
        "eaqi_classic", "eaqi_eea_2024", "who_2021", "eu_2024_2881", "eu_2008_50_ec",
    }
    # index authorities are single dicts; WHO/EU are lists of windows.
    assert prov["eaqi_classic"]["band"] == "poor"        # 30 in 25-50 (classic)
    assert prov["eaqi_classic"]["averaging"] == "24-hour"
    assert prov["eaqi_eea_2024"]["band"] == "moderate"   # 30 in 16-50 (revised)
    assert isinstance(prov["who_2021"], list)
    who_windows = {(e["averaging"], e["value"]) for e in prov["who_2021"]}
    assert who_windows == {("annual", 5), ("24-hour", 15)}
    assert all(e["exceeds"] for e in prov["who_2021"])     # 30 > both
    assert all("basis" in e and "interim_targets" in e for e in prov["who_2021"])


def test_band_provenance_eu_milestones_distinct_and_repealed_tagged():
    prov = band_provenance("pm2_5", 30)
    in_force = prov["eu_2024_2881"]
    repealed = prov["eu_2008_50_ec"]
    assert all(e["status"] == "in force" for e in in_force)
    assert all(e["status"] == "repealed" for e in repealed)
    assert all("attain_by" in e for e in in_force)
    # 30 > the 2030 annual limit (10) but not the 2026 annual limit (25)? 30>25 too.
    annual_2030 = next(e for e in in_force
                       if e["averaging"] == "calendar year" and e["attain_by"] == "2030-01-01")
    assert annual_2030["value"] == 10 and annual_2030["exceeds"] is True


def test_band_provenance_who_independent_of_eu():
    # pm2_5 @ 12: over WHO 24h (15)? no (12<15). Over WHO annual (5)? yes.
    prov = band_provenance("pm2_5", 12)
    who = {(e["averaging"], e["exceeds"]) for e in prov["who_2021"]}
    assert who == {("annual", True), ("24-hour", False)}


def test_band_provenance_co_has_who_retained_hour_values_no_eaqi():
    prov = band_provenance("carbon_monoxide", 5000)
    assert "eaqi_classic" not in prov and "eaqi_eea_2024" not in prov
    assert {(e["averaging"], e["value"]) for e in prov["who_retained"]} == {
        ("8-hour", 10000), ("1-hour", 35000), ("15-minute", 100000),
    }
    who21 = prov["who_2021"]
    assert who21[0]["averaging"] == "24-hour" and who21[0]["value"] == 4000


def test_band_provenance_european_aqi_index_only():
    prov = band_provenance("european_aqi", 55)
    assert set(prov) == {"eaqi_classic"}
    assert prov["eaqi_classic"]["band"] == "moderate"
    assert prov["eaqi_classic"]["averaging"] == "aggregate"


def test_band_provenance_none_value_is_empty():
    assert band_provenance("pm2_5", None) == {}


# === CO ppm conversion =====================================================


def test_co_ugm3_to_ppm_conversion():
    expected = round(4000 * 24.04 / 28.01 / 1000.0, 4)
    assert co_ugm3_to_ppm(4000) == expected
    assert 3.0 < co_ugm3_to_ppm(4000) < 3.6


def test_co_ugm3_to_ppm_none_and_zero():
    assert co_ugm3_to_ppm(None) is None
    assert co_ugm3_to_ppm(0) == 0.0
