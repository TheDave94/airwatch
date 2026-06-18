"""Unit tests for the pure AirWatch analytics functions (HA-free)."""

from __future__ import annotations

import pytest

from custom_components.airwatch.analytics import (
    LEVEL_LABELS,
    compute_recent_percentile,
    consensus,
    daily_peaks,
    level_for_source,
    level_label,
    percentile_rank,
    recent_percentile_from_series,
)
from custom_components.airwatch.sources.base import PollutantSeries

# --- daily_peaks -----------------------------------------------------------


def test_daily_peaks_takes_per_day_max_and_skips_none():
    times = [
        "2026-05-29T00:00",
        "2026-05-29T12:00",
        "2026-05-30T06:00",
        "2026-05-30T18:00",
        "2026-05-31T03:00",
    ]
    values = [10.0, 20.8, 5.0, None, 0.0]
    assert daily_peaks(times, values) == [
        ("2026-05-29", 20.8),
        ("2026-05-30", 5.0),
        ("2026-05-31", 0.0),
    ]


def test_daily_peaks_empty():
    assert daily_peaks([], []) == []


# --- percentile_rank -------------------------------------------------------


def test_percentile_rank_midrank():
    dist = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert percentile_rank(4.0, dist) == pytest.approx(90.0)  # (4 + 0.5)/5*100
    assert percentile_rank(0.0, dist) == pytest.approx(10.0)  # (0 + 0.5)/5*100
    assert percentile_rank(2.0, dist) == pytest.approx(50.0)
    assert percentile_rank(5.0, dist) == pytest.approx(100.0)


def test_percentile_rank_empty():
    assert percentile_rank(1.0, []) is None


# --- recent_percentile -----------------------------------------------------


def _peaks(n: int, today_value: float) -> list[tuple[str, float]]:
    # n distinct days ending today; today's peak is today_value.
    days = [f"2026-03-{d:02d}" for d in range(1, n)]
    pairs = [(d, 1.0) for d in days]
    pairs.append(("2026-04-01", today_value))
    return pairs


def test_recent_percentile_ok():
    peaks = _peaks(20, 9.0)  # 19 days at 1.0 + today at 9.0 = 20 days
    res = compute_recent_percentile(peaks, "2026-04-01", min_days=14)
    assert res.status == "ok"
    assert res.days == 20
    assert res.percentile == pytest.approx(100.0 * (19 + 0.5) / 20)


def test_recent_percentile_insufficient_history():
    peaks = _peaks(10, 9.0)  # only 10 days < min 14
    res = compute_recent_percentile(peaks, "2026-04-01", min_days=14)
    assert res.status == "insufficient_history"
    assert res.percentile is None
    assert res.days == 10


def test_recent_percentile_no_today_data():
    peaks = [("2026-03-01", 1.0), ("2026-03-02", 2.0)]
    res = compute_recent_percentile(peaks, "2026-04-01", min_days=1)
    assert res.status == "no_data"
    assert res.percentile is None


def test_recent_percentile_off_season_when_window_all_zero():
    # 15 days, every day zero (incl today) -> off_season, no number.
    peaks = [(f"2026-01-{d:02d}", 0.0) for d in range(1, 16)]
    res = compute_recent_percentile(peaks, "2026-01-15", min_days=14)
    assert res.status == "off_season"
    assert res.percentile is None
    assert res.days == 15


def test_recent_percentile_quiet_today_with_signal_window_is_low_not_off_season():
    # Window has signal (days 1..14 nonzero); today is 0 -> genuinely low, ok.
    peaks = [(f"2026-01-{d:02d}", float(d)) for d in range(1, 15)]
    peaks.append(("2026-01-15", 0.0))  # today = 0
    res = compute_recent_percentile(peaks, "2026-01-15", min_days=14)
    assert res.status == "ok"
    assert res.percentile is not None
    assert res.percentile < 10  # at the bottom of a signal-bearing window
    assert res.percentile != 50


def test_recent_percentile_from_series_hourly_to_daily():
    # 16 days of hourly-ish data (two readings/day); today's peak is the max.
    times, values = [], []
    for d in range(1, 17):
        date = f"2026-03-{d:02d}"
        times += [f"{date}T03:00", f"{date}T15:00"]
        peak = 9.0 if d == 16 else 1.0
        values += [0.0, peak]  # overnight zero + daytime peak
    res = recent_percentile_from_series(times, values, "2026-03-16", min_days=14)
    assert res.status == "ok"
    assert res.days == 16  # one per day, not per hour
    assert res.percentile == pytest.approx(100.0 * (15 + 0.5) / 16)


def test_recent_percentile_from_series_trims_window():
    times = [f"2026-01-{d:02d}T12:00" for d in range(1, 11)]
    values = [1.0] * 10
    res = recent_percentile_from_series(
        times, values, "2026-01-10", window_days=5, min_days=3
    )
    assert res.days == 5  # only the trailing 5 days kept


# --- consensus / tiebreak --------------------------------------------------


def test_consensus_equal_levels_good():
    res = consensus({"open_meteo": 0, "sensor_community": 0})
    assert res.state == "good"
    assert res.level == 0
    assert res.diverged is False


def test_consensus_equal_high():
    res = consensus({"open_meteo": 2, "sensor_community": 2})
    assert res.state == "high"
    assert res.level == 2
    assert res.diverged is False


def test_consensus_adjacent_takes_higher():
    # 0 & 1 -> elevated (the higher); 1 & 2 -> high (the higher).
    assert consensus({"a": 0, "b": 1}).state == "elevated"
    assert consensus({"a": 0, "b": 1}).level == 1
    assert consensus({"a": 1, "b": 2}).state == "high"
    assert consensus({"a": 1, "b": 2}).level == 2


def test_consensus_two_apart_is_mixed():
    res = consensus({"open_meteo": 0, "sensor_community": 2})
    assert res.state == "mixed"
    assert res.level is None
    assert res.diverged is True


def test_consensus_single_source_passes_through():
    res = consensus({"open_meteo": 2}, max_possible=3)
    assert res.state == "high"          # pass-through of level 2
    assert res.level == 2
    assert res.diverged is False        # nothing to disagree with
    assert res.source_levels == {"open_meteo": 2}
    assert res.source_count == 1
    assert res.max_possible == 3


def test_consensus_zero_sources_omitted():
    res = consensus({}, max_possible=3)
    assert res.state is None
    assert res.level is None
    assert res.diverged is False
    assert res.source_levels == {}
    assert res.source_count == 0
    assert res.max_possible == 3


def test_consensus_reports_source_levels():
    res = consensus({"open_meteo": 2, "land_steiermark": 1})
    assert res.source_levels == {"open_meteo": 2, "land_steiermark": 1}
    assert res.state == "high"  # adjacent -> higher


def test_consensus_three_sources_all_agree():
    res = consensus({"open_meteo": 1, "sensor_community": 1, "land_steiermark": 1})
    assert res.state == "elevated"
    assert res.level == 1
    assert res.diverged is False


def test_consensus_three_sources_lone_high_outlier_takes_higher():
    # {1,1,2}: take-the-higher makes the lone outlier win (-> high), divergence
    # stays OFF (spread is only 1). Documented health-conservative tiebreak.
    res = consensus({"open_meteo": 1, "sensor_community": 1, "land_steiermark": 2})
    assert res.state == "high"
    assert res.level == 2
    assert res.diverged is False


def test_consensus_three_sources_spanning_two_levels_is_mixed():
    res = consensus({"open_meteo": 0, "sensor_community": 0, "land_steiermark": 2})
    assert res.state == "mixed"
    assert res.diverged is True


def test_consensus_default_max_possible_is_source_count():
    res = consensus({"open_meteo": 1, "sensor_community": 1})
    assert res.max_possible == 2


# --- level_for_source ------------------------------------------------------


def _series(current: float | None) -> PollutantSeries:
    return PollutantSeries(pollutant="pm2_5", unit="µg/m³", current=current, values=[])


def test_level_for_source_buckets_current_value():
    # pm2_5 EAQI bounds (10,20,25,50,75); bands→levels {1,2→0; 3,4→1; 5,6→2}.
    assert level_for_source("open_meteo", "pm2_5", _series(5.0)) == 0   # band 1
    assert level_for_source("open_meteo", "pm2_5", _series(22.0)) == 1  # band 3
    assert level_for_source("open_meteo", "pm2_5", _series(80.0)) == 2  # band 6


def test_level_for_source_none_current_returns_none():
    assert level_for_source("open_meteo", "pm2_5", _series(None)) is None


def test_level_for_source_co_uses_who_eu_bounds():
    co = PollutantSeries(pollutant="carbon_monoxide", unit="µg/m³", current=4500.0, values=[])
    assert level_for_source("open_meteo", "carbon_monoxide", co) == 1


# --- level_label -----------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (0, "good"),
        (1, "elevated"),
        (2, "high"),
        (None, None),  # None in -> None out (explicit guard)
        (3, None),  # out-of-range -> None (LEVEL_LABELS.get miss)
        (-1, None),  # out-of-range -> None
        (99, None),  # far out-of-range -> None
    ],
)
def test_level_label_maps_levels_and_passes_through_none(level, expected):
    assert level_label(level) == expected


def test_level_labels_table():
    assert LEVEL_LABELS == {0: "good", 1: "elevated", 2: "high"}
