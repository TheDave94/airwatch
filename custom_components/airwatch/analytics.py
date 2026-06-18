"""Derived analytics for AirWatch — pure, Home Assistant-free.

All cross-source comparison happens on a common 3-level scale:
    0 = good (below WHO/EAQI elevated band), 1 = elevated, 2 = high.
Each source reports µg/m³ (or the european_aqi index); the common level comes
from :func:`pollutant_registry.level_for_value`, which collapses the EAQI 6-band
scale (and the WHO/EU bounds for CO) onto these 3 levels. Raw per-source values
are never reconstructed from a level.

These functions take values in and return numbers out — no HA, no I/O — so they
are unit-tested in isolation like the source parsers. The consensus / divergence
/ recent-percentile math is a verbatim PORT of PollenWatch's; only the bucketing
input changed (pollutant bands instead of pollen thresholds).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .sources.pollutant_registry import level_for_value

if TYPE_CHECKING:
    from .sources.base import PollutantSeries

#: Trailing window for recent_percentile (rolling days, relative to today).
PERCENTILE_WINDOW_DAYS = 92
#: Minimum distinct days of data before a percentile is emitted (else
#: "insufficient history"). ~2 weeks.
MIN_PERCENTILE_DAYS = 14


#: Canonical human-readable labels for the 3-level scale.
LEVEL_LABELS: dict[int, str] = {0: "good", 1: "elevated", 2: "high"}


def level_label(level: int | None) -> str | None:
    """Human-readable label for an int level. ``None`` in → ``None`` out."""
    if level is None:
        return None
    return LEVEL_LABELS.get(level)


def level_for_source(
    source_key: str, pollutant: str, series: PollutantSeries
) -> int | None:
    """Bucket one source's reading for one pollutant to the common 0/1/2 level.

    Single source of truth for every consumer that needs a severity bucket:
    the analytics consensus pass and the raw-sensor ``level`` attribute. Unlike
    PollenWatch (which had per-source categorical scales — DWD strings, PI/Google
    indices), every AirWatch source reports a concentration (µg/m³) or the EAQI
    index, so all sources bucket through the same band logic.

    Returns ``None`` when the current value is missing or the pollutant has no
    band mapping for this value.
    """
    if series.current is None:
        return None
    return level_for_value(pollutant, series.current)


def daily_peaks(
    times: list[str], values: list[float | None]
) -> list[tuple[str, float]]:
    """Group an aligned (times, values) series into per-day peak values.

    Returns ``(date, peak)`` pairs sorted by date; ``None`` values are skipped.
    Peaks (per-day max), not hourly values, are the population for percentiles.
    """
    peaks: dict[str, float] = {}
    for time, value in zip(times, values, strict=False):
        if value is None:
            continue
        date = time[:10]
        peaks[date] = max(peaks.get(date, value), value)
    return sorted(peaks.items())


def percentile_rank(value: float, distribution: list[float]) -> float | None:
    """Empirical percentile rank of ``value`` within ``distribution`` (0–100).

    Midrank ("mean") convention with linear tie handling:
    ``100 * (count(x < value) + 0.5 * count(x == value)) / n``. ``None`` for an
    empty distribution.
    """
    n = len(distribution)
    if n == 0:
        return None
    less = sum(1 for x in distribution if x < value)
    equal = sum(1 for x in distribution if x == value)
    return 100.0 * (less + 0.5 * equal) / n


@dataclass(slots=True)
class PercentileResult:
    """Outcome of a recent_percentile computation."""

    percentile: float | None
    days: int
    status: str  # "ok" | "insufficient_history" | "off_season" | "no_data"


def compute_recent_percentile(
    peaks: list[tuple[str, float]],
    today: str,
    *,
    min_days: int = MIN_PERCENTILE_DAYS,
) -> PercentileResult:
    """Rank today's daily peak against the window's daily-peak distribution.

    ``peaks`` is the daily-peak series already limited to the trailing window
    (``daily_peaks`` output, dates ≤ today). The distribution includes today.

    Statuses (state is a number only for ``ok``):
    - ``no_data`` — today's value is missing from the window.
    - ``insufficient_history`` — fewer than ``min_days`` distinct days.
    - ``off_season`` — the **whole window is zero** (max == 0): a percentile
      would be a misreadable 50%. Keyed on the window max, not today: a zero
      *today* in a window that has signal is a genuine informative low percentile
      and stays ``ok``.
    - ``ok`` — a real percentile.
    """
    by_date = dict(peaks)
    today_peak = by_date.get(today)
    if today_peak is None:
        return PercentileResult(None, len(by_date), "no_data")
    if len(by_date) < min_days:
        return PercentileResult(None, len(by_date), "insufficient_history")
    distribution = list(by_date.values())
    if max(distribution) == 0:
        return PercentileResult(None, len(by_date), "off_season")
    return PercentileResult(
        percentile_rank(today_peak, distribution), len(by_date), "ok"
    )


# --- consensus / divergence (cross-source) --------------------------------

# Categorical consensus vocabulary. Levels 0/1/2 map to good/elevated/high;
# "mixed" is genuine disagreement (sources differ by >1 level) — a number can't
# hold it.
CONSENSUS_GOOD = "good"
CONSENSUS_ELEVATED = "elevated"
CONSENSUS_HIGH = "high"
CONSENSUS_MIXED = "mixed"
CONSENSUS_OPTIONS = [
    CONSENSUS_GOOD, CONSENSUS_ELEVATED, CONSENSUS_HIGH, CONSENSUS_MIXED,
]
_LEVEL_TO_CONSENSUS = {0: CONSENSUS_GOOD, 1: CONSENSUS_ELEVATED, 2: CONSENSUS_HIGH}


@dataclass(slots=True)
class ConsensusResult:
    """Cross-source consensus for one pollutant.

    Single-source pollutants are also represented (state = that source's own
    level mapped to good/elevated/high; ``diverged`` always False; the n/m badge
    on the sensor tells the user it's single-source). ``source_count`` is how
    many sources actually contributed; ``max_possible`` is the global ceiling
    from the pollutant registry (used by the card for the badge denominator).
    """

    state: str | None        # one of CONSENSUS_OPTIONS, or None if 0 sources
    level: int | None        # 0/1/2 when single or agreed; None for mixed/0
    diverged: bool           # True only in the "mixed" case (levels differ by >1)
    source_levels: dict[str, int]  # contributing per-source levels
    source_count: int        # len(source_levels) — how many contributed now
    max_possible: int        # global ceiling from pollutant_registry


def consensus(levels: dict[str, int], max_possible: int = 0) -> ConsensusResult:
    """Combine per-source levels (0/1/2) into a consensus.

    Equal weighting. Tiebreak (deliberate, health-conservative): equal → that
    level; adjacent (differ by 1) → the **higher** level; differ by >1 → "mixed".

    Source-count semantics:
    - 0 sources: state=None, level=None, source_count=0 (sensor unavailable).
    - 1 source: pass-through — state = that source's level; never "mixed", never
      diverged. The n/m badge tells the user this is single-source.
    - >=2 sources: the consensus logic above.

    ``max_possible`` is the registry ceiling (how many sources GLOBALLY cover
    this pollutant); defaults to ``source_count`` if not provided.
    """
    source_levels = dict(levels)
    source_count = len(source_levels)
    if max_possible == 0:
        max_possible = source_count or 1
    if source_count == 0:
        return ConsensusResult(None, None, False, source_levels, 0, max_possible)
    if source_count == 1:
        level = next(iter(source_levels.values()))
        return ConsensusResult(
            _LEVEL_TO_CONSENSUS[level], level, False, source_levels,
            1, max_possible,
        )
    values = list(source_levels.values())
    if max(values) - min(values) > 1:
        return ConsensusResult(
            CONSENSUS_MIXED, None, True, source_levels,
            source_count, max_possible,
        )
    level = max(values)  # take-the-higher on equal/adjacent
    return ConsensusResult(
        _LEVEL_TO_CONSENSUS[level], level, False, source_levels,
        source_count, max_possible,
    )


def recent_percentile_from_series(
    times: list[str],
    values: list[float | None],
    today: str,
    *,
    window_days: int = PERCENTILE_WINDOW_DAYS,
    min_days: int = MIN_PERCENTILE_DAYS,
) -> PercentileResult:
    """recent_percentile for a source that carries its own history series.

    Daily-peaks the aligned (times, values), keeps the trailing ``window_days``
    up to and including ``today``, and ranks today within it. (Open-Meteo's
    92-day backfill path.)
    """
    peaks = [(d, p) for d, p in daily_peaks(times, values) if d <= today]
    return compute_recent_percentile(
        peaks[-window_days:], today, min_days=min_days
    )
