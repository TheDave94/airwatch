"""Unit tests for the pure pollutant registry (HA-free).

Exercises the band/threshold helpers: EAQI band boundaries, the EAQI→3-level
collapse used by consensus, the WHO 2021 exceedance overlay, and the CO ppm
convenience conversion.
"""

from __future__ import annotations

import pytest

from custom_components.airwatch.sources.pollutant_registry import (
    BandAuthority,
    band_provenance,
    co_ugm3_to_ppm,
    eaqi_band_colour,
    eaqi_band_for,
    eaqi_band_label,
    eu_guideline_for,
    level_for_value,
    who_assessment_for,
    who_guideline_for,
)

# --- eaqi_band_for ---------------------------------------------------------
# pm2_5 bounds: (10, 20, 25, 50, 75) -> bands 1..5 by <=, else 6.


@pytest.mark.parametrize(
    ("value", "band"),
    [
        (0, 1),
        (10, 1),     # on the bound -> still band 1 (<=)
        (10.01, 2),  # just over -> band 2
        (20, 2),
        (20.01, 3),
        (25, 3),
        (25.01, 4),
        (50, 4),
        (50.01, 5),
        (75, 5),
        (75.01, 6),  # above the last bound -> band 6
        (500, 6),
    ],
)
def test_eaqi_band_for_pm2_5_boundaries(value, band):
    assert eaqi_band_for("pm2_5", value) == band


def test_eaqi_band_for_european_aqi_index_bounds():
    # european_aqi banded on its own 20/40/60/80/100 index scale.
    assert eaqi_band_for("european_aqi", 0) == 1
    assert eaqi_band_for("european_aqi", 20) == 1
    assert eaqi_band_for("european_aqi", 20.5) == 2
    assert eaqi_band_for("european_aqi", 100) == 5
    assert eaqi_band_for("european_aqi", 101) == 6


def test_eaqi_band_for_none_and_co_and_unknown_return_none():
    assert eaqi_band_for("pm2_5", None) is None
    # CO is not in the EAQI -> None.
    assert eaqi_band_for("carbon_monoxide", 5000) is None
    # Unknown pollutant key -> None.
    assert eaqi_band_for("not_a_pollutant", 10) is None


def test_eaqi_band_label():
    assert eaqi_band_label(1) == "good"
    assert eaqi_band_label(6) == "extremely_poor"
    assert eaqi_band_label(None) is None
    assert eaqi_band_label(7) is None  # out of range


# --- level_for_value (EAQI 6-band -> 3-level collapse) ---------------------
# bands {1,2}->0, {3,4}->1, {5,6}->2.


@pytest.mark.parametrize(
    ("value", "level"),
    [
        (5, 0),      # band 1 -> good
        (15, 0),     # band 2 -> good
        (22, 1),     # band 3 -> elevated
        (40, 1),     # band 4 -> elevated
        (60, 2),     # band 5 -> high
        (90, 2),     # band 6 -> high
    ],
)
def test_level_for_value_pm2_5_collapse(value, level):
    assert level_for_value("pm2_5", value) == level


def test_level_for_value_none_returns_none():
    assert level_for_value("pm2_5", None) is None


def test_level_for_value_unknown_pollutant_returns_none():
    assert level_for_value("not_a_pollutant", 10) is None


@pytest.mark.parametrize(
    ("value", "level"),
    [
        (0, 0),
        (3999, 0),     # below WHO 24h (4000)
        (4000, 1),     # WHO 24h onset -> elevated
        (9999, 1),
        (10000, 2),    # EU 8h legal limit -> high
        (50000, 2),
    ],
)
def test_level_for_value_carbon_monoxide_who_eu_bounds(value, level):
    assert level_for_value("carbon_monoxide", value) == level


# --- who_assessment_for ----------------------------------------------------


def test_who_assessment_for_pm2_5_exceedance():
    # WHO pm2_5 24h guideline = 15 µg/m³.
    below = who_assessment_for("pm2_5", 14.9)
    assert below is not None
    assert below.guideline == 15
    assert below.averaging == "24-hour"
    assert below.exceeds is False
    assert below.authority == BandAuthority.WHO_2021.value

    at = who_assessment_for("pm2_5", 15)
    assert at.exceeds is True  # >= guideline counts as exceedance

    above = who_assessment_for("pm2_5", 30)
    assert above.exceeds is True


def test_who_assessment_for_none_value_or_no_guideline():
    assert who_assessment_for("pm2_5", None) is None
    # european_aqi has no WHO guideline (it's an index).
    assert who_assessment_for("european_aqi", 50) is None


def test_who_assessment_for_carbon_monoxide():
    a = who_assessment_for("carbon_monoxide", 5000)
    assert a is not None
    assert a.guideline == 4000
    assert a.exceeds is True


def test_who_guideline_for():
    g = who_guideline_for("ozone")
    assert g is not None
    assert g.value == 100
    assert g.averaging == "8-hour"
    assert who_guideline_for("european_aqi") is None


# --- co_ugm3_to_ppm --------------------------------------------------------


def test_co_ugm3_to_ppm_conversion():
    # ppm = µg/m³ * 24.04 / 28.01 / 1000, rounded to 4 dp.
    expected = round(4000 * 24.04 / 28.01 / 1000.0, 4)
    assert co_ugm3_to_ppm(4000) == expected
    # Sanity: 4000 µg/m³ CO is ~3.4 ppm.
    assert 3.0 < co_ugm3_to_ppm(4000) < 3.6


def test_co_ugm3_to_ppm_none_and_zero():
    assert co_ugm3_to_ppm(None) is None
    assert co_ugm3_to_ppm(0) == 0.0


# --- eaqi_band_colour ------------------------------------------------------


def test_eaqi_band_colour():
    assert eaqi_band_colour(1) == "#50f0e6"
    assert eaqi_band_colour(6) == "#7d2181"
    assert eaqi_band_colour(None) is None
    assert eaqi_band_colour(0) is None  # out of range


# --- eu_guideline_for ------------------------------------------------------


def test_eu_guideline_for():
    no2 = eu_guideline_for("nitrogen_dioxide")
    assert no2 is not None
    assert no2.value == 200
    assert no2.averaging == "1-hour"
    # CO EU limit is the 8-hour 10 mg/m³ value.
    assert eu_guideline_for("carbon_monoxide").value == 10000
    # european_aqi (an index) has no EU concentration limit.
    assert eu_guideline_for("european_aqi") is None


# --- band_provenance: authorities distinct, each carries value+averaging ----


def test_band_provenance_concentration_pollutant_has_all_three_authorities():
    # pm2_5 @ 30 µg/m³: in the EAQI, over WHO 24h (15), over EU annual (25).
    prov = band_provenance("pm2_5", 30)
    assert set(prov) == {"eaqi", "who_2021", "eu_limit"}
    # each authority is tagged and carries its averaging window — not collapsed
    assert prov["eaqi"]["authority"] == BandAuthority.EAQI.value
    assert prov["eaqi"]["band"] == "poor"
    assert prov["eaqi"]["averaging"] == "24-hour"
    assert prov["eaqi"]["colour"] == "#ff5050"
    assert prov["who_2021"]["authority"] == BandAuthority.WHO_2021.value
    assert prov["who_2021"]["value"] == 15
    assert prov["who_2021"]["averaging"] == "24-hour"
    assert prov["who_2021"]["exceeds"] is True
    assert prov["eu_limit"]["authority"] == BandAuthority.EU_LIMIT.value
    assert prov["eu_limit"]["value"] == 25
    assert prov["eu_limit"]["averaging"] == "annual"
    assert prov["eu_limit"]["exceeds"] is True


def test_band_provenance_who_and_eu_are_independent_not_collapsed():
    # pm2_5 @ 20: over WHO (15) but under EU annual (25) — the two authorities
    # must disagree, proving they are not collapsed into one verdict.
    prov = band_provenance("pm2_5", 20)
    assert prov["who_2021"]["exceeds"] is True
    assert prov["eu_limit"]["exceeds"] is False


def test_band_provenance_co_has_who_eu_but_no_eaqi():
    # CO is absent from the EAQI but carries WHO + EU bands.
    prov = band_provenance("carbon_monoxide", 5000)
    assert "eaqi" not in prov
    assert prov["who_2021"]["value"] == 4000
    assert prov["who_2021"]["exceeds"] is True
    assert prov["eu_limit"]["value"] == 10000
    assert prov["eu_limit"]["exceeds"] is False  # 5000 < 10000


def test_band_provenance_european_aqi_index_only():
    # european_aqi is an index — EAQI band only, no WHO/EU concentration bands.
    prov = band_provenance("european_aqi", 55)
    assert set(prov) == {"eaqi"}
    assert prov["eaqi"]["band"] == "moderate"
    assert prov["eaqi"]["averaging"] == "aggregate"


def test_band_provenance_none_value_is_empty():
    assert band_provenance("pm2_5", None) == {}
