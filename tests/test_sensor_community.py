"""Unit tests for the Sensor.Community source (HA-free, offline).

Covers the hard-won robustness reused from packages/air_quality.yaml: SDS011
fault rejection (999.9 / non-positive), staleness rejection, mean over valid
stations only, and "unknown if all invalid". HTTP is mocked via the source's
injectable transport, so these run offline and deterministically.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.airwatch.sources.base import (
    SourceStatus,
    SourceUnavailable,
)
from custom_components.airwatch.sources.sensor_community import (
    SensorCommunitySource,
    StationReading,
    _valid_or_none,
    aggregate,
    parse_station,
)

_NOW = datetime(2026, 6, 18, 21, 50, 0, tzinfo=UTC)


def _ts(minutes_ago: int = 1) -> str:
    return (_NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _reading(pm25: str | None, pm10: str | None, *, minutes_ago: int = 1,
             sensor_id: int = 11111, lat: str = "48.21", lon: str = "16.37") -> dict:
    datavalues = []
    if pm10 is not None:
        datavalues.append({"value_type": "P1", "value": pm10})
    if pm25 is not None:
        datavalues.append({"value_type": "P2", "value": pm25})
    return {
        "timestamp": _ts(minutes_ago),
        "location": {"latitude": lat, "longitude": lon},
        "sensor": {"id": sensor_id, "sensor_type": {"name": "SDS011"}},
        "sensordatavalues": datavalues,
    }


# --- fault window ----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5.0, 5.0),
        (0.1, 0.1),
        (899.9, 899.9),
        (0.0, None),       # non-positive rejected
        (-3.0, None),      # negative rejected
        (900.0, None),     # ceiling rejected
        (999.9, None),     # the SDS011 stuck-at-max fault value
        (None, None),
    ],
)
def test_valid_or_none_fault_window(value, expected):
    assert _valid_or_none(value) == expected


# --- parse_station ---------------------------------------------------------


def test_parse_station_extracts_p1_p2():
    reading = parse_station(
        [_reading("3.7", "7.0")], ["pm2_5", "pm10"],
        now=_NOW, requested_lat=48.21, requested_lon=16.37,
    )
    assert reading is not None
    assert reading.values == {"pm2_5": 3.7, "pm10": 7.0}
    assert reading.sensor_id == 11111
    assert reading.distance_km is not None and reading.distance_km < 5


def test_parse_station_rejects_999_fault_per_pollutant():
    # PM2.5 faulted (999.9) but PM10 valid → only PM10 survives.
    reading = parse_station(
        [_reading("999.9", "12.0")], ["pm2_5", "pm10"],
        now=_NOW, requested_lat=48.21, requested_lon=16.37,
    )
    assert reading is not None
    assert "pm2_5" not in reading.values
    assert reading.values == {"pm10": 12.0}


def test_parse_station_picks_latest_reading():
    older = _reading("50.0", "60.0", minutes_ago=4)
    newer = _reading("3.7", "7.0", minutes_ago=1)
    reading = parse_station(
        [older, newer], ["pm2_5", "pm10"],
        now=_NOW, requested_lat=48.21, requested_lon=16.37,
    )
    assert reading.values == {"pm2_5": 3.7, "pm10": 7.0}  # the newer one


def test_parse_station_stale_reading_rejected():
    # Latest reading is 120 min old; default max_age 60 → rejected entirely.
    reading = parse_station(
        [_reading("3.7", "7.0", minutes_ago=120)], ["pm2_5", "pm10"],
        now=_NOW, requested_lat=48.21, requested_lon=16.37,
    )
    assert reading is None


def test_parse_station_empty_array_returns_none():
    assert parse_station(
        [], ["pm2_5"], now=_NOW, requested_lat=48.21, requested_lon=16.37
    ) is None


def test_parse_station_honours_pollutant_selection():
    # Only pm2_5 requested → pm10 ignored even though present.
    reading = parse_station(
        [_reading("3.7", "7.0")], ["pm2_5"],
        now=_NOW, requested_lat=48.21, requested_lon=16.37,
    )
    assert reading.values == {"pm2_5": 3.7}


# --- aggregate -------------------------------------------------------------


def _sr(sensor_id: int, **values: float) -> StationReading:
    return StationReading(
        sensor_id=sensor_id, latitude=48.21, longitude=16.37,
        distance_km=1.0, timestamp=_ts(), values=values,
    )


def test_aggregate_means_over_valid_stations():
    result = aggregate(
        [_sr(1, pm2_5=4.0, pm10=8.0), _sr(2, pm2_5=6.0, pm10=10.0)],
        ["pm2_5", "pm10"],
        requested_lat=48.21, requested_lon=16.37, now_iso="2026-06-18T21:50:00",
    )
    assert result.status is SourceStatus.OK
    assert result.pollutants["pm2_5"].current == 5.0   # (4+6)/2
    assert result.pollutants["pm10"].current == 9.0     # (8+10)/2
    assert result.pollutants["pm2_5"].native == "2 station(s)"
    assert "1" in result.station and "2" in result.station


def test_aggregate_one_bad_station_degrades_to_rest():
    # Station 2 has no valid pm2_5 (it faulted upstream, so absent from values).
    result = aggregate(
        [_sr(1, pm2_5=4.0), _sr(2, pm10=10.0)],
        ["pm2_5", "pm10"],
        requested_lat=48.21, requested_lon=16.37, now_iso="2026-06-18T21:50:00",
    )
    assert result.pollutants["pm2_5"].current == 4.0   # only station 1
    assert result.pollutants["pm2_5"].native == "1 station(s)"
    assert result.pollutants["pm10"].current == 10.0


def test_aggregate_all_invalid_is_out_of_coverage():
    result = aggregate(
        [], ["pm2_5", "pm10"],
        requested_lat=48.21, requested_lon=16.37, now_iso="2026-06-18T21:50:00",
    )
    assert result.status is SourceStatus.OUT_OF_COVERAGE
    assert result.pollutants == {}
    assert result.message and "no valid" in result.message.lower()


# --- SensorCommunitySource (explicit stations, injected transport) ---------


def _transport_map(payloads: dict[str, object]):
    """Transport that returns a payload chosen by substring match on the URL."""
    def transport(url: str, timeout: float):
        for needle, payload in payloads.items():
            if needle in url:
                return 200, payload
        return 200, []
    return transport


def test_source_explicit_stations_fault_rejecting_mean():
    src = SensorCommunitySource(
        48.21, 16.37, ["pm2_5", "pm10"],
        stations=[11111, 22222],
        transport=_transport_map({
            "/sensor/11111/": [_reading("4.0", "8.0")],
            # 22222: pm2_5 faulted (999.9) → dropped; pm10 valid.
            "/sensor/22222/": [_reading("999.9", "12.0")],
        }),
        now_fn=lambda: _NOW,
    )
    result = src.fetch()
    assert result.status is SourceStatus.OK
    assert result.pollutants["pm2_5"].current == 4.0    # only 11111 valid
    assert result.pollutants["pm10"].current == 10.0    # (8+12)/2


def test_source_all_stations_offline_is_out_of_coverage():
    src = SensorCommunitySource(
        48.21, 16.37, ["pm2_5"],
        stations=[11111, 22222],
        transport=_transport_map({}),  # every station returns []
        now_fn=lambda: _NOW,
    )
    result = src.fetch()
    assert result.status is SourceStatus.OUT_OF_COVERAGE


def test_source_all_transport_failures_raise_unavailable():
    def failing(url: str, timeout: float):
        raise ConnectionError("down")

    src = SensorCommunitySource(
        48.21, 16.37, ["pm2_5"], stations=[11111], transport=failing,
        retry_delay=0, now_fn=lambda: _NOW,
    )
    with pytest.raises(SourceUnavailable):
        src.fetch()


def test_source_validate_drops_non_pm_pollutants():
    src = SensorCommunitySource(48.21, 16.37, ["pm2_5", "ozone", "carbon_monoxide"])
    assert src.pollutants == ["pm2_5"]


def test_source_validate_stations_parses_ints():
    src = SensorCommunitySource(
        48.21, 16.37, ["pm2_5"], stations=["11111", "x", 22222]
    )
    assert src.stations == [11111, 22222]


# --- discovery (area filter) -----------------------------------------------


def test_source_discovery_picks_nearest_in_range():
    # Three sensors at increasing distance; max_stations=2 keeps the 2 nearest.
    area = [
        _reading("5.0", "9.0", sensor_id=1, lat="48.211", lon="16.370"),   # ~0.1 km
        _reading("6.0", "10.0", sensor_id=2, lat="48.230", lon="16.400"),  # ~3 km
        _reading("7.0", "11.0", sensor_id=3, lat="48.440", lon="16.730"),  # ~38 km (out)
    ]
    src = SensorCommunitySource(
        48.21, 16.37, ["pm2_5"],
        max_distance_km=10, max_stations=2,
        transport=_transport_map({"/filter/area=": area}),
        now_fn=lambda: _NOW,
    )
    result = src.fetch()
    assert result.status is SourceStatus.OK
    # sensor 3 is out of range; 1 and 2 average: (5+6)/2 = 5.5
    assert result.pollutants["pm2_5"].current == 5.5
    assert "1" in result.station and "2" in result.station and "3" not in result.station
