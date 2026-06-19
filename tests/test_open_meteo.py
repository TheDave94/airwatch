"""Unit tests for the Open-Meteo (CAMS) air-quality source client.

All HTTP is mocked via the source's injectable transport, so these tests run
offline and deterministically.
"""

from __future__ import annotations

import asyncio
import urllib.error

import pytest

from custom_components.airwatch.sources.base import (
    SourceResponseError,
    SourceStatus,
    SourceUnavailable,
)
from custom_components.airwatch.sources.open_meteo import OpenMeteoSource


def _european_payload() -> dict:
    """A trimmed but realistic successful Open-Meteo air-quality response.

    Coordinates are snapped (48.2082 -> 48.2, 16.3738 -> 16.4). The pm2_5
    series ends in a ``None`` to mirror the forecast horizon running out.
    """
    times = [
        "2026-05-29T12:00",
        "2026-05-29T13:00",
        "2026-05-29T14:00",
        "2026-05-29T15:00",
    ]
    return {
        "latitude": 48.2,
        "longitude": 16.4,
        "timezone": "Europe/Vienna",
        "elevation": 363.0,
        "hourly_units": {"pm2_5": "µg/m³", "ozone": "µg/m³"},
        "current": {"time": "2026-05-29T14:00", "pm2_5": 12.4, "ozone": 80.1},
        "hourly": {
            "time": times,
            "pm2_5": [10.0, 11.2, 12.4, None],
            "ozone": [70.0, 75.5, 80.1, 79.0],
        },
    }


def _transport_returning(status: int, payload: object):
    """Build a transport that records calls and returns a fixed response."""
    calls: list[tuple[str, float]] = []

    def transport(url: str, timeout: float):
        calls.append((url, timeout))
        return status, payload

    transport.calls = calls  # type: ignore[attr-defined]
    return transport


def test_success_for_european_coords_parses_series():
    source = OpenMeteoSource(
        48.2082, 16.3738, ["pm2_5", "ozone"],
        transport=_transport_returning(200, _european_payload()),
    )
    result = source.fetch()

    assert result.ok
    assert result.status is SourceStatus.OK
    assert result.source == "open_meteo"
    # snapped coordinates surfaced and shift computed
    assert result.snapped_lat == 48.2
    assert result.snapped_lon == 16.4
    assert result.coordinate_shift_km is not None
    assert 1.0 < result.coordinate_shift_km < 4.0
    # both requested pollutants present with aligned values + current
    assert set(result.pollutants) == {"pm2_5", "ozone"}
    pm = result.pollutants["pm2_5"]
    assert pm.unit == "µg/m³"
    assert pm.current == 12.4
    assert pm.values == [10.0, 11.2, 12.4, None]
    # forecast split lands on the "current" timestamp
    assert result.forecast_split == 2


def test_out_of_coverage_returns_status_not_raise():
    transport = _transport_returning(
        400, {"error": True, "reason": "No data is available for this location"}
    )
    source = OpenMeteoSource(40.71, -74.0, ["pm2_5"], transport=transport)

    result = source.fetch()  # must not raise

    assert result.status is SourceStatus.OUT_OF_COVERAGE
    assert not result.ok
    assert result.pollutants == {}
    assert result.message and "no data" in result.message.lower()


def test_unexpected_error_reason_raises_response_error():
    transport = _transport_returning(
        400, {"error": True, "reason": "Invalid hourly variable foo"}
    )
    source = OpenMeteoSource(48.21, 16.37, ["pm2_5"], transport=transport)

    with pytest.raises(SourceResponseError):
        source.fetch()


def test_network_error_retries_once_then_succeeds():
    calls = {"n": 0}

    def flaky_transport(url: str, timeout: float):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("temporary failure")
        return 200, _european_payload()

    source = OpenMeteoSource(
        48.21, 16.37, ["pm2_5"], transport=flaky_transport, retry_delay=0
    )
    result = source.fetch()

    assert calls["n"] == 2  # initial attempt + one retry
    assert result.ok


def test_network_error_exhausts_retries_and_raises_unavailable():
    calls = {"n": 0}

    def always_fails(url: str, timeout: float):
        calls["n"] += 1
        raise urllib.error.URLError("down")

    source = OpenMeteoSource(
        48.21, 16.37, ["pm2_5"], transport=always_fails, retry_delay=0
    )
    with pytest.raises(SourceUnavailable):
        source.fetch()

    assert calls["n"] == 2  # tried exactly twice, no infinite loop


def test_unknown_pollutant_silent_dropped_at_construction():
    """OM silent-drops pollutants it doesn't cover (matching every other
    source). The orchestrator passes the user's GLOBAL selection; OM takes only
    the keys it can. Raising would block any install selecting a pollutant OM
    doesn't cover."""
    source = OpenMeteoSource(
        48.21, 16.37, ["pm2_5", "ozone", "pollen_birch", "noise"]
    )
    assert source.pollutants == ["pm2_5", "ozone"]


def test_past_days_clamped_to_provider_maximum():
    source = OpenMeteoSource(48.21, 16.37, ["pm2_5"], past_days=999)
    assert source.past_days == 92
    assert "past_days=92" in source.build_url()
    assert "domains=cams_europe" in source.build_url()


def test_parse_is_pure_and_handles_european_aqi_index():
    payload = {
        "latitude": 48.2,
        "longitude": 16.4,
        "timezone": "Europe/Vienna",
        "hourly_units": {"european_aqi": ""},
        "current": {"time": "2026-05-29T14:00", "european_aqi": 42},
        "hourly": {"time": ["2026-05-29T14:00"], "european_aqi": [42]},
    }
    source = OpenMeteoSource(48.2082, 16.3738, ["european_aqi"])
    result = source.parse(payload)
    assert result.status is SourceStatus.OK
    assert result.pollutants["european_aqi"].current == 42
    assert result.pollutants["european_aqi"].values == [42]


# -- async fetch path --------------------------------------------------------


def _async_transport_returning(status: int, payload: object):
    async def transport(url: str, timeout: float):
        return status, payload

    return transport


def test_async_success_parses_series():
    source = OpenMeteoSource(
        48.2082, 16.3738, ["pm2_5", "ozone"],
        async_transport=_async_transport_returning(200, _european_payload()),
    )
    result = asyncio.run(source.async_fetch())

    assert result.ok
    assert result.status is SourceStatus.OK
    assert result.pollutants["pm2_5"].current == 12.4
    assert result.pollutants["pm2_5"].values == [10.0, 11.2, 12.4, None]
    assert result.forecast_split == 2


def test_async_out_of_coverage_returns_status_not_raise():
    source = OpenMeteoSource(
        40.71, -74.0, ["pm2_5"],
        async_transport=_async_transport_returning(
            400, {"error": True, "reason": "No data is available for this location"}
        ),
    )
    result = asyncio.run(source.async_fetch())

    assert result.status is SourceStatus.OUT_OF_COVERAGE
    assert result.pollutants == {}


def test_async_retries_once_then_succeeds():
    calls = {"n": 0}

    async def flaky(url: str, timeout: float):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("temporary")
        return 200, _european_payload()

    source = OpenMeteoSource(
        48.21, 16.37, ["pm2_5"], async_transport=flaky, retry_delay=0
    )
    result = asyncio.run(source.async_fetch())

    assert calls["n"] == 2
    assert result.ok


def test_async_exhausts_retries_and_raises_unavailable():
    calls = {"n": 0}

    async def always_fails(url: str, timeout: float):
        calls["n"] += 1
        raise ConnectionError("down")  # OSError subclass

    source = OpenMeteoSource(
        48.21, 16.37, ["pm2_5"], async_transport=always_fails, retry_delay=0
    )
    with pytest.raises(SourceUnavailable):
        asyncio.run(source.async_fetch())

    assert calls["n"] == 2
