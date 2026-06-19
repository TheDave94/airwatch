"""Sensor.Community (hyperlocal SDS011 cluster) — AirWatch SECONDARY source.

Sensor.Community is a citizen network of low-cost particulate sensors (mostly
Nova Fitness SDS011). Each sensor's REST endpoint
``https://data.sensor.community/airrohr/v1/sensor/<id>/`` returns the last ~5
minutes of readings as a JSON array; an empty array means the station is
offline. The area-filter endpoint
``https://data.sensor.community/airrohr/v1/filter/area=<lat>,<lon>,<km>`` returns
the same shape for every sensor within a radius — used for auto-discovery when no
station IDs are configured.

Robustness reuse
----------------
This source reproduces, in the integration's source-contract form, the
hard-won robustness of the live in-HA-config REST sensor
(``homeassistant-config: packages/air_quality.yaml``, live-verified 2026-06-18):

- **SDS011 fault rejection** — a reading is valid only if ``0 < value < 900``.
  This drops the SDS011 stuck-at-max fault value (999.9) *and* non-positive
  readings, exactly as the YAML's ``0 < v < 900`` mean filter does.
- **Mean over valid stations only** — each pollutant's value is the mean of the
  stations that returned a valid reading; one bad station degrades to the mean
  of the rest.
- **Unknown if all invalid** — a pollutant with no valid station contributes no
  series; if no pollutant has any valid station, the fetch is reported as
  unavailable rather than emitting a misleading number.
- **Staleness handling** — the API only serves the last ~5 minutes, but each
  reading also carries a UTC ``timestamp``; a reading older than
  ``max_age_minutes`` is rejected (belt-and-suspenders against a stuck feed).

Like ``open_meteo.py`` this module is HA-free and has an injectable transport, so
``parse``/aggregation are pure and unit-testable offline. Run it directly::

    python -m custom_components.airwatch.sources.sensor_community --lat 48.2082 --lon 16.3738
    python -m custom_components.airwatch.sources.sensor_community --stations <sensor-id>,<sensor-id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import aiohttp

from .base import (
    PollutantSeries,
    SourceResult,
    SourceStatus,
    SourceUnavailable,
    _haversine_km,
)

SOURCE_NAME = "sensor_community"

#: Sensor.Community covers particulates only (SDS011). PM2.5 = value_type "P2",
#: PM10 = "P1" in the API's ``sensordatavalues``.
SUPPORTED_POLLUTANTS: tuple[str, ...] = ("pm2_5", "pm10")
_VALUE_TYPE: dict[str, str] = {"pm2_5": "P2", "pm10": "P1"}

#: SDS011 fault / validity window. A reading counts only if ``0 < v < 900`` —
#: rejects the SDS011 stuck-at-max fault (999.9) and non-positive values. This is
#: the exact rule from the live ``packages/air_quality.yaml`` mean filter.
FAULT_CEILING: float = 900.0

_SENSOR_URL = "https://data.sensor.community/airrohr/v1/sensor/{sid}/"
_AREA_URL = "https://data.sensor.community/airrohr/v1/filter/area={lat},{lon},{km}"

#: Defaults for auto-discovery (no explicit station IDs configured).
DEFAULT_MAX_DISTANCE_KM: float = 10.0
DEFAULT_MAX_STATIONS: int = 5
#: A reading older than this (relative to fetch time) is rejected as stale.
DEFAULT_MAX_AGE_MIN: int = 60

#: ``transport(url, timeout) -> (status_code, parsed_json)``. Network failures
#: raise ``OSError`` so the fetch can classify them; HTTP error bodies are
#: returned as ``(code, body)``. Mirrors :mod:`open_meteo`.
Transport = Callable[[str, float], "tuple[int, Any]"]
AsyncTransport = Callable[[str, float], Awaitable["tuple[int, Any]"]]


def _http_get_json(url: str, timeout: float) -> tuple[int, Any]:
    """Default synchronous transport built on the standard library."""
    req = urllib.request.Request(url, headers={"User-Agent": "AirWatch/0.0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        try:
            return err.code, json.loads(raw)
        except json.JSONDecodeError:
            return err.code, {"error": True, "reason": raw[:200]}


def _async_retryable_exceptions() -> tuple[type[BaseException], ...]:
    retryable: tuple[type[BaseException], ...] = (asyncio.TimeoutError, OSError)
    try:
        import aiohttp
    except ImportError:
        return retryable
    return (*retryable, aiohttp.ClientError)


# -- pure parsing / aggregation ---------------------------------------------


@dataclass(slots=True)
class StationReading:
    """One station's latest valid reading after fault + staleness filtering."""

    sensor_id: int | None
    latitude: float | None
    longitude: float | None
    distance_km: float | None
    timestamp: str | None
    #: pollutant key -> validated µg/m³ value (only valid pollutants present).
    values: dict[str, float] = field(default_factory=dict)


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _valid_or_none(value: float | None) -> float | None:
    """Apply the SDS011 fault/validity window: keep only ``0 < v < 900``."""
    if value is None:
        return None
    if 0 < value < FAULT_CEILING:
        return value
    return None


def _latest_reading(readings: list[dict]) -> dict | None:
    """Pick the most recent reading from a sensor's array (max timestamp).

    Sensor.Community timestamps are ``"YYYY-MM-DD HH:MM:SS"`` UTC strings, which
    sort lexically in chronological order, so a plain ``max`` is correct.
    """
    dated = [r for r in readings if isinstance(r, dict) and r.get("timestamp")]
    if not dated:
        return None
    return max(dated, key=lambda r: r["timestamp"])


def _reading_fresh(timestamp: str | None, now: datetime, max_age_min: int) -> bool:
    if not timestamp:
        return False
    try:
        ts = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return False
    return timedelta(0) <= (now - ts) <= timedelta(minutes=max_age_min)


def parse_station(
    readings: list[dict],
    pollutants: Iterable[str],
    *,
    now: datetime,
    requested_lat: float,
    requested_lon: float,
    max_age_min: int = DEFAULT_MAX_AGE_MIN,
) -> StationReading | None:
    """Reduce one sensor's reading array to its latest valid :class:`StationReading`.

    Pure. Returns ``None`` when the station has no readings or its latest reading
    is stale. A returned reading may still carry an empty ``values`` dict (all
    pollutants faulted) — the aggregator drops those per pollutant.
    """
    latest = _latest_reading(readings)
    if latest is None:
        return None
    timestamp = latest.get("timestamp")
    if not _reading_fresh(timestamp, now, max_age_min):
        return None

    datavalues = latest.get("sensordatavalues") or []
    by_type = {dv.get("value_type"): dv.get("value") for dv in datavalues}
    values: dict[str, float] = {}
    for pollutant in pollutants:
        raw = by_type.get(_VALUE_TYPE.get(pollutant, ""))
        valid = _valid_or_none(_coerce_float(raw))
        if valid is not None:
            values[pollutant] = valid

    location = latest.get("location") or {}
    lat = _coerce_float(location.get("latitude"))
    lon = _coerce_float(location.get("longitude"))
    distance = (
        _haversine_km(requested_lat, requested_lon, lat, lon)
        if lat is not None and lon is not None
        else None
    )
    sensor = latest.get("sensor") or {}
    sensor_id = sensor.get("id")
    return StationReading(
        sensor_id=sensor_id if isinstance(sensor_id, int) else None,
        latitude=lat,
        longitude=lon,
        distance_km=distance,
        timestamp=timestamp,
        values=values,
    )


def _group_area_by_sensor(payload: list[dict]) -> dict[int, list[dict]]:
    """Group an area-filter response (many sensors) into per-sensor arrays."""
    grouped: dict[int, list[dict]] = {}
    for reading in payload:
        if not isinstance(reading, dict):
            continue
        sensor = reading.get("sensor") or {}
        sid = sensor.get("id")
        if isinstance(sid, int):
            grouped.setdefault(sid, []).append(reading)
    return grouped


def aggregate(
    stations: list[StationReading],
    pollutants: Iterable[str],
    *,
    requested_lat: float,
    requested_lon: float,
    now_iso: str,
) -> SourceResult:
    """Combine per-station readings into a fault-rejecting mean SourceResult.

    Each pollutant's value is the mean over the stations that reported a valid
    reading for it (``unknown if all invalid`` → the pollutant is omitted). The
    overall status is OK if at least one pollutant has a contributing station,
    else OUT_OF_COVERAGE.
    """
    pollutant_set = list(pollutants)
    series: dict[str, PollutantSeries] = {}
    contributing: set[int] = set()
    for pollutant in pollutant_set:
        vals = [s.values[pollutant] for s in stations if pollutant in s.values]
        if not vals:
            continue
        mean = round(sum(vals) / len(vals), 1)
        series[pollutant] = PollutantSeries(
            pollutant=pollutant,
            unit="µg/m³",
            current=mean,
            values=[mean],
            # native carries the per-pollutant station count — the integration's
            # equivalent of the YAML's ``stations_valid`` attribute.
            native=f"{len(vals)} station(s)",
        )
        for s in stations:
            if pollutant in s.values and s.sensor_id is not None:
                contributing.add(s.sensor_id)

    if not series:
        return SourceResult(
            source=SOURCE_NAME,
            status=SourceStatus.OUT_OF_COVERAGE,
            requested_lat=requested_lat,
            requested_lon=requested_lon,
            generated_at=now_iso,
            message="No valid Sensor.Community readings from nearby stations.",
        )

    ids = sorted(contributing)
    station_label = (
        f"mean of {len(ids)} station(s): {', '.join(str(i) for i in ids)}"
        if ids
        else "mean of nearby stations"
    )
    return SourceResult(
        source=SOURCE_NAME,
        status=SourceStatus.OK,
        requested_lat=requested_lat,
        requested_lon=requested_lon,
        times=[now_iso],
        current_time=now_iso,
        pollutants=series,
        generated_at=now_iso,
        station=station_label,
    )


# -- source client ----------------------------------------------------------


class SensorCommunitySource:
    """Hyperlocal particulate source aggregating nearby Sensor.Community sensors.

    With explicit ``stations`` it fetches each ``/v1/sensor/<id>/`` endpoint (the
    deterministic, proven approach from ``packages/air_quality.yaml``). Without
    them it auto-discovers nearby sensors via the area filter, ranks by distance,
    and keeps the nearest ``max_stations`` within ``max_distance_km``.
    """

    name = SOURCE_NAME
    # Real-time point source: no own history series, and not recorder-baselined
    # in v1 (it still feeds consensus/divergence — those need a level, not a
    # percentile). recent_percentile can be added later by flipping these.
    supports_history = False
    provides_history_series = False

    def __init__(
        self,
        latitude: float,
        longitude: float,
        pollutants: Iterable[str] | None = None,
        *,
        stations: Iterable[int | str] | None = None,
        max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
        max_stations: int = DEFAULT_MAX_STATIONS,
        max_age_min: int = DEFAULT_MAX_AGE_MIN,
        timeout: float = 30.0,
        retry_delay: float = 1.0,
        transport: Transport | None = None,
        async_transport: AsyncTransport | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.latitude = float(latitude)
        self.longitude = float(longitude)
        self.pollutants = self._validate_pollutants(pollutants)
        self.stations = self._validate_stations(stations)
        self.max_distance_km = float(max_distance_km)
        self.max_stations = max(1, int(max_stations))
        self.max_age_min = max(1, int(max_age_min))
        self.timeout = timeout
        self.retry_delay = retry_delay
        self._transport: Transport = transport or _http_get_json
        self._async_transport: AsyncTransport | None = async_transport
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    @staticmethod
    def _validate_pollutants(pollutants: Iterable[str] | None) -> list[str]:
        # Silent-drop the non-particulate pollutants (Sensor.Community is PM
        # only) — same pattern as OpenMeteoSource.
        if pollutants is None:
            return list(SUPPORTED_POLLUTANTS)
        return [p for p in pollutants if p in _VALUE_TYPE]

    @staticmethod
    def _validate_stations(stations: Iterable[int | str] | None) -> list[int]:
        if not stations:
            return []
        out: list[int] = []
        for s in stations:
            try:
                out.append(int(s))
            except (TypeError, ValueError):
                continue
        return out

    # -- URL building --------------------------------------------------------

    def _area_url(self) -> str:
        return _AREA_URL.format(
            lat=_fmt_coord(self.latitude),
            lon=_fmt_coord(self.longitude),
            km=_fmt_distance(self.max_distance_km),
        )

    def _sensor_url(self, sid: int) -> str:
        return _SENSOR_URL.format(sid=sid)

    # -- fetching ------------------------------------------------------------

    def fetch(self) -> SourceResult:
        """Synchronous fetch (standalone entry point + tests)."""
        readings_by_station = self._collect_sync()
        return self._build(readings_by_station)

    async def async_fetch(
        self, session: aiohttp.ClientSession | None = None
    ) -> SourceResult:
        """Async fetch for Home Assistant. Mirrors :meth:`fetch`."""
        if self._async_transport is not None:
            readings = await self._collect_async(self._async_transport)
            return self._build(readings)

        import aiohttp

        owns_session = session is None
        if owns_session:
            session = aiohttp.ClientSession()
        try:
            transport = self._make_aiohttp_transport(aiohttp, session)
            readings = await self._collect_async(transport)
            return self._build(readings)
        finally:
            if owns_session:
                await session.close()

    # -- collection (explicit stations vs area discovery) -------------------

    def _collect_sync(self) -> dict[int, list[dict]]:
        if self.stations:
            out: dict[int, list[dict]] = {}
            for sid in self.stations:
                payload = self._get_sync(self._sensor_url(sid))
                out[sid] = payload if isinstance(payload, list) else []
            return out
        payload = self._get_sync(self._area_url())
        return self._select_discovered(payload if isinstance(payload, list) else [])

    async def _collect_async(
        self, transport: AsyncTransport
    ) -> dict[int, list[dict]]:
        if self.stations:
            results = await asyncio.gather(
                *(
                    self._get_async(transport, self._sensor_url(sid))
                    for sid in self.stations
                ),
                return_exceptions=True,
            )
            out: dict[int, list[dict]] = {}
            failures = 0
            for sid, payload in zip(self.stations, results, strict=True):
                if isinstance(payload, BaseException) or not isinstance(payload, list):
                    failures += 1
                    out[sid] = []
                else:
                    out[sid] = payload
            # All explicit stations failed at transport level → transient.
            if failures == len(self.stations):
                raise SourceUnavailable(
                    f"All {failures} Sensor.Community station requests failed."
                )
            return out
        payload = await self._get_async(transport, self._area_url())
        return self._select_discovered(payload if isinstance(payload, list) else [])

    def _select_discovered(self, area_payload: list[dict]) -> dict[int, list[dict]]:
        """From an area-filter response, keep the nearest PM sensors in range."""
        grouped = _group_area_by_sensor(area_payload)
        ranked: list[tuple[float, int, list[dict]]] = []
        for sid, readings in grouped.items():
            latest = _latest_reading(readings)
            if latest is None:
                continue
            # Only PM sensors (those reporting P1/P2) are useful here.
            types = {
                dv.get("value_type")
                for dv in (latest.get("sensordatavalues") or [])
            }
            if not types & set(_VALUE_TYPE.values()):
                continue
            location = latest.get("location") or {}
            lat = _coerce_float(location.get("latitude"))
            lon = _coerce_float(location.get("longitude"))
            if lat is None or lon is None:
                continue
            distance = _haversine_km(self.latitude, self.longitude, lat, lon)
            if distance > self.max_distance_km:
                continue
            ranked.append((distance, sid, readings))
        ranked.sort(key=lambda t: t[0])
        return {sid: readings for _d, sid, readings in ranked[: self.max_stations]}

    def _build(self, readings_by_station: dict[int, list[dict]]) -> SourceResult:
        now = self._now_fn()
        stations: list[StationReading] = []
        for readings in readings_by_station.values():
            parsed = parse_station(
                readings,
                self.pollutants,
                now=now,
                requested_lat=self.latitude,
                requested_lon=self.longitude,
                max_age_min=self.max_age_min,
            )
            if parsed is not None:
                stations.append(parsed)
        return aggregate(
            stations,
            self.pollutants,
            requested_lat=self.latitude,
            requested_lon=self.longitude,
            now_iso=now.isoformat(timespec="seconds"),
        )

    # -- transports ----------------------------------------------------------

    def _get_sync(self, url: str) -> Any:
        attempts = 2
        for attempt in range(attempts):
            try:
                _status, payload = self._transport(url, self.timeout)
                return payload
            except OSError as err:
                if attempt + 1 < attempts:
                    import time

                    time.sleep(self.retry_delay)
                    continue
                raise SourceUnavailable(
                    f"Sensor.Community request failed after {attempts} attempts: {err}"
                ) from err
        return None

    async def _get_async(self, transport: AsyncTransport, url: str) -> Any:
        retryable = _async_retryable_exceptions()
        attempts = 2
        for attempt in range(attempts):
            try:
                _status, payload = await transport(url, self.timeout)
                return payload
            except retryable as err:
                if attempt + 1 < attempts:
                    await asyncio.sleep(self.retry_delay)
                    continue
                raise SourceUnavailable(
                    f"Sensor.Community request failed after {attempts} attempts: {err}"
                ) from err
        return None

    def _make_aiohttp_transport(
        self, aiohttp_mod: Any, session: aiohttp.ClientSession
    ) -> AsyncTransport:
        async def transport(url: str, timeout: float) -> tuple[int, Any]:
            client_timeout = aiohttp_mod.ClientTimeout(total=timeout)
            async with session.get(
                url, headers={"User-Agent": "AirWatch/0.1.0"}, timeout=client_timeout
            ) as resp:
                text = await resp.text()
                try:
                    return resp.status, json.loads(text)
                except json.JSONDecodeError:
                    return resp.status, {"error": True, "reason": text[:200]}

        return transport


def _fmt_coord(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _fmt_distance(value: float) -> str:
    return f"{value:g}"


# -- standalone entry point --------------------------------------------------


def _summarise(result: SourceResult) -> str:
    lines = [f"AirWatch · Sensor.Community — status: {result.status.value}"]
    lines.append(f"  requested: {result.requested_lat:.4f}, {result.requested_lon:.4f}")
    if result.status is not SourceStatus.OK:
        if result.message:
            lines.append(f"  message:   {result.message}")
        return "\n".join(lines)
    lines.append(f"  stations:  {result.station}")
    lines.append(f"  time:      {result.current_time}")
    lines.append("")
    lines.append(f"  {'pollutant':<10} {'mean':>8}  unit   stations")
    lines.append(f"  {'-' * 10} {'-' * 8}  {'-' * 5}  {'-' * 8}")
    for key, series in result.pollutants.items():
        cur = "n/a" if series.current is None else f"{series.current:.1f}"
        lines.append(f"  {key:<10} {cur:>8}  {series.unit}  {series.native}")
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe Sensor.Community for a location or station set.",
    )
    parser.add_argument("--lat", type=float, default=48.2082, help="latitude")
    parser.add_argument("--lon", type=float, default=16.3738, help="longitude")
    parser.add_argument(
        "--stations",
        default="",
        help="comma-separated station IDs (omit to auto-discover by distance)",
    )
    parser.add_argument("--max-distance-km", type=float, default=DEFAULT_MAX_DISTANCE_KM)
    args = parser.parse_args(argv)

    stations = [s.strip() for s in args.stations.split(",") if s.strip()] or None
    source = SensorCommunitySource(
        args.lat, args.lon, stations=stations, max_distance_km=args.max_distance_km
    )
    if stations:
        print(f"GET per-station: {[source._sensor_url(int(s)) for s in stations]}\n")
    else:
        print(f"GET {source._area_url()}\n")
    result = source.fetch()
    print(_summarise(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
