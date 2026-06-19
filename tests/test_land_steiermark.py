"""Unit tests for the Land Steiermark drift-anchor source (HA-free, offline).

Covers the parsing of the Austrian SensorThings harvest, the validity +
staleness filters, nearest-*usable*-station selection, and the honest
drift-anchor result shape (lag surfaced; stale/invalid data → OUT_OF_COVERAGE
with an accurate reason rather than a misleading "current" value). HTTP is
mocked via the source's injectable transport, so these run offline and
deterministically.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.airwatch.sources.base import (
    SourceStatus,
    SourceUnavailable,
)
from custom_components.airwatch.sources.land_steiermark import (
    CADENCE,
    LandSteiermarkSource,
    StationObservation,
    _parse_phenomenon_end,
    _valid_value,
    build_result,
    parse_discovery,
    parse_things,
    select_station,
)

_NOW = datetime(2026, 6, 19, 12, 0, 0, tzinfo=UTC)
_GRAZ_LAT, _GRAZ_LON = 47.07, 15.44


def _pt(hours_ago: float) -> str:
    """A SensorThings phenomenonTime interval whose END is `hours_ago` before _NOW."""
    end = _NOW - timedelta(hours=hours_ago)
    start = end - timedelta(hours=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return f"{start.strftime(fmt)}/{end.strftime(fmt)}"


def _datastream(op_name: str, result: float, hours_ago: float, *,
                local_id: str = "STA.06.164", name: str = "Graz Don Bosco",
                lat: float = 47.055611, lon: float = 15.416603) -> dict:
    return {
        "Thing": {
            "name": name,
            "properties": {"localId": local_id, "countryCode": "AT"},
            "Locations": [{"location": {"type": "Point", "coordinates": [lon, lat]}}],
        },
        "ObservedProperty": {"name": op_name},
        "Observations": [{"phenomenonTime": _pt(hours_ago), "result": result}],
    }


def _things_payload(local_id: str, name: str, lat: float, lon: float,
                    streams: list[tuple[str, float, float]]) -> dict:
    return {
        "value": [
            {
                "name": name,
                "properties": {"localId": local_id, "countryCode": "AT"},
                "Locations": [
                    {"location": {"type": "Point", "coordinates": [lon, lat]}}
                ],
                "Datastreams": [
                    {
                        "ObservedProperty": {"name": op},
                        "Observations": [
                            {"phenomenonTime": _pt(h), "result": val}
                        ],
                    }
                    for op, val, h in streams
                ],
            }
        ]
    }


# --- validity + time parsing ----------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (6.6, 6.6),
        (0.1, 0.1),
        (0.0, None),     # exact zero = missing in this dataset
        (-2.0, None),    # negative rejected
        (None, None),
    ],
)
def test_valid_value(value, expected):
    assert _valid_value(value) == expected


def test_parse_phenomenon_end_interval_uses_end():
    end = _parse_phenomenon_end("2026-06-10T06:00:00Z/2026-06-10T07:00:00Z")
    assert end == datetime(2026, 6, 10, 7, 0, 0, tzinfo=UTC)


def test_parse_phenomenon_end_instant_and_naive():
    assert _parse_phenomenon_end("2026-06-10T07:00:00Z") == datetime(
        2026, 6, 10, 7, 0, 0, tzinfo=UTC
    )
    # naive instant is assumed UTC
    assert _parse_phenomenon_end("2026-06-10T07:00:00") == datetime(
        2026, 6, 10, 7, 0, 0, tzinfo=UTC
    )


def test_parse_phenomenon_end_bad_input():
    assert _parse_phenomenon_end("") is None
    assert _parse_phenomenon_end(None) is None
    assert _parse_phenomenon_end("not-a-time") is None


# --- parse_discovery -------------------------------------------------------


def test_parse_discovery_groups_streams_by_station():
    payload = {
        "value": [
            _datastream("PM10", 6.6, 2.0),
            _datastream("NO2", 29.3, 2.0),
            _datastream("PM10", 7.0, 1.0, local_id="STA.06.018",
                        name="Graz Schloßberg", lat=47.073, lon=15.437),
        ]
    }
    stations = parse_discovery(
        payload, ["pm10", "nitrogen_dioxide"],
        requested_lat=_GRAZ_LAT, requested_lon=_GRAZ_LON,
    )
    by_id = {s.local_id: s for s in stations}
    assert set(by_id) == {"STA.06.164", "STA.06.018"}
    donbosco = by_id["STA.06.164"]
    assert set(donbosco.readings) == {"pm10", "nitrogen_dioxide"}
    assert donbosco.readings["pm10"][0] == 6.6
    assert donbosco.distance_km is not None and donbosco.distance_km < 5


def test_parse_discovery_ignores_unrequested_pollutant():
    payload = {"value": [_datastream("O3", 80.0, 1.0)]}
    stations = parse_discovery(
        payload, ["pm10"], requested_lat=_GRAZ_LAT, requested_lon=_GRAZ_LON
    )
    # Station still registered (so it can be diagnosed), but with no readings.
    assert len(stations) == 1
    assert stations[0].readings == {}


def test_parse_discovery_dedupes_keeping_newest():
    payload = {
        "value": [
            _datastream("PM10", 99.0, 50.0),  # older
            _datastream("PM10", 6.6, 1.0),    # newer
        ]
    }
    stations = parse_discovery(
        payload, ["pm10"], requested_lat=_GRAZ_LAT, requested_lon=_GRAZ_LON
    )
    assert stations[0].readings["pm10"][0] == 6.6


# --- parse_things (explicit station) ---------------------------------------


def test_parse_things_extracts_datastreams():
    payload = _things_payload(
        "STA.06.164", "Graz Don Bosco", 47.0556, 15.4166,
        [("PM10", 6.6, 2.0), ("NO2", 29.3, 2.0)],
    )
    stations = parse_things(
        payload, ["pm10", "nitrogen_dioxide"],
        requested_lat=_GRAZ_LAT, requested_lon=_GRAZ_LON,
    )
    assert len(stations) == 1
    s = stations[0]
    assert s.local_id == "STA.06.164"
    assert set(s.readings) == {"pm10", "nitrogen_dioxide"}


# --- select_station --------------------------------------------------------


def _station(local_id, dist, readings) -> StationObservation:
    return StationObservation(
        local_id=local_id, name=local_id, latitude=47.0, longitude=15.0,
        distance_km=dist, readings=readings,
    )


def test_select_prefers_nearest_usable_over_nearer_unusable():
    near_unusable = _station("A", 0.6, {})  # nearest but nothing valid
    far_usable = _station("B", 2.4, {"pm10": (6.6, _NOW - timedelta(hours=2))})
    chosen = select_station(
        [near_unusable, far_usable],
        max_distance_km=25, now=_NOW, max_age_hours=72, explicit=False,
    )
    assert chosen.local_id == "B"


def test_select_fallback_prefers_any_valid_for_diagnostics():
    # Nearest has only invalid (0) data; next has valid-but-stale → pick the
    # valid-but-stale one so the message can surface the real feed lag.
    nearest_invalid = _station("A", 0.5, {"pm10": (0.0, _NOW - timedelta(hours=2))})
    stale_valid = _station("B", 1.0, {"pm10": (6.6, _NOW - timedelta(hours=300))})
    chosen = select_station(
        [nearest_invalid, stale_valid],
        max_distance_km=25, now=_NOW, max_age_hours=72, explicit=False,
    )
    assert chosen.local_id == "B"


def test_select_out_of_range_returns_none():
    far = _station("A", 40.0, {"pm10": (6.6, _NOW)})
    assert select_station(
        [far], max_distance_km=25, now=_NOW, max_age_hours=72, explicit=False
    ) is None


def test_select_explicit_returns_single():
    s = _station("STA.06.164", 99.0, {})
    assert select_station(
        [s], max_distance_km=1, now=_NOW, max_age_hours=72, explicit=True
    ) is s


# --- build_result ----------------------------------------------------------


def test_build_result_ok_surfaces_lag_in_native():
    s = _station("STA.06.164", 2.4, {"pm10": (6.6, _NOW - timedelta(hours=48))})
    result = build_result(
        s, ["pm10"], requested_lat=_GRAZ_LAT, requested_lon=_GRAZ_LON,
        now=_NOW, max_age_hours=72,
    )
    assert result.status is SourceStatus.OK
    series = result.pollutants["pm10"]
    assert series.current == 6.6
    assert series.unit == "µg/m³"
    assert "STA.06.164" in series.native and "old" in series.native
    assert "drift anchor" in result.station


def test_build_result_no_station_out_of_coverage():
    result = build_result(
        None, ["pm10"], requested_lat=_GRAZ_LAT, requested_lon=_GRAZ_LON,
        now=_NOW, max_age_hours=72,
    )
    assert result.status is SourceStatus.OUT_OF_COVERAGE
    assert result.pollutants == {}
    assert "within range" in (result.message or "")


def test_build_result_stale_reports_lag():
    s = _station("STA.06.164", 2.4, {"pm10": (6.6, _NOW - timedelta(hours=216))})
    result = build_result(
        s, ["pm10"], requested_lat=_GRAZ_LAT, requested_lon=_GRAZ_LON,
        now=_NOW, max_age_hours=72,
    )
    assert result.status is SourceStatus.OUT_OF_COVERAGE
    assert "days old" in (result.message or "")
    assert "9.0" in (result.message or "")  # 216h = 9.0 days


def test_build_result_all_invalid_reports_no_valid():
    s = _station("STA.06.164", 2.4, {"pm10": (0.0, _NOW - timedelta(hours=2))})
    result = build_result(
        s, ["pm10"], requested_lat=_GRAZ_LAT, requested_lon=_GRAZ_LON,
        now=_NOW, max_age_hours=72,
    )
    assert result.status is SourceStatus.OUT_OF_COVERAGE
    assert "no valid" in (result.message or "").lower()


# --- LandSteiermarkSource (injected transport) -----------------------------


def test_source_flags_mark_drift_anchor():
    src = LandSteiermarkSource(_GRAZ_LAT, _GRAZ_LON, ["pm10"])
    assert src.cadence == CADENCE == "drift_anchor"
    assert src.supports_history is False
    assert src.provides_history_series is False


def test_source_validate_drops_unsupported_pollutants():
    src = LandSteiermarkSource(
        _GRAZ_LAT, _GRAZ_LON, ["pm10", "european_aqi", "bogus"]
    )
    assert src.pollutants == ["pm10"]


def test_source_empty_pollutants_out_of_coverage():
    src = LandSteiermarkSource(_GRAZ_LAT, _GRAZ_LON, ["european_aqi"])
    result = src.fetch()
    assert result.status is SourceStatus.OUT_OF_COVERAGE


def _transport(payload: dict):
    def transport(url: str, timeout: float):
        return 200, payload
    return transport


def test_source_discovery_ok_picks_nearest_usable():
    payload = {
        "value": [
            # nearest but all-invalid (0.0)
            _datastream("PM10", 0.0, 2.0, local_id="STA.06.018",
                        name="Schloßberg", lat=47.073, lon=15.437),
            # slightly farther, valid + fresh
            _datastream("PM10", 6.6, 2.0),
        ]
    }
    src = LandSteiermarkSource(
        _GRAZ_LAT, _GRAZ_LON, ["pm10"],
        transport=_transport(payload), now_fn=lambda: _NOW,
    )
    result = src.fetch()
    assert result.status is SourceStatus.OK
    assert result.pollutants["pm10"].current == 6.6
    assert "STA.06.164" in result.station


def test_source_discovery_all_stale_out_of_coverage():
    payload = {"value": [_datastream("PM10", 6.6, 216.0)]}  # 9 days old
    src = LandSteiermarkSource(
        _GRAZ_LAT, _GRAZ_LON, ["pm10"],
        transport=_transport(payload), now_fn=lambda: _NOW,
    )
    result = src.fetch()
    assert result.status is SourceStatus.OUT_OF_COVERAGE
    assert "days old" in (result.message or "")


def test_source_explicit_station_ok():
    payload = _things_payload(
        "STA.06.164", "Graz Don Bosco", 47.0556, 15.4166,
        [("PM10", 6.6, 2.0)],
    )
    src = LandSteiermarkSource(
        _GRAZ_LAT, _GRAZ_LON, ["pm10"], station="STA.06.164",
        transport=_transport(payload), now_fn=lambda: _NOW,
    )
    result = src.fetch()
    assert result.status is SourceStatus.OK
    assert result.pollutants["pm10"].current == 6.6


def test_source_transport_failure_raises_unavailable():
    def failing(url: str, timeout: float):
        raise ConnectionError("down")

    src = LandSteiermarkSource(
        _GRAZ_LAT, _GRAZ_LON, ["pm10"], transport=failing,
        retry_delay=0, now_fn=lambda: _NOW,
    )
    with pytest.raises(SourceUnavailable):
        src.fetch()


# --- URL building ----------------------------------------------------------


def test_discovery_url_scopes_region_and_pollutants():
    src = LandSteiermarkSource(_GRAZ_LAT, _GRAZ_LON, ["pm10", "nitrogen_dioxide"])
    url = src.discovery_url()
    assert "/Datastreams?" in url
    assert "STA.06" in url
    # ObservedProperty names are URL-encoded; the request targets the harvest.
    assert "PM10" in url and "NO2" in url


def test_station_url_targets_things_by_local_id():
    src = LandSteiermarkSource(_GRAZ_LAT, _GRAZ_LON, ["pm10"], station="STA.06.164")
    url = src.station_url("STA.06.164")
    assert "/Things?" in url
    assert "STA.06.164" in url
