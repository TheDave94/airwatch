"""Land Steiermark official stations — AirWatch SECONDARY source (DRIFT ANCHOR).

This is the third AirWatch source: the official Austrian air-quality monitoring
network's Styrian (Steiermark) stations, reached through the **OGC SensorThings
API** harvest of the Umweltbundesamt / Land feeds maintained by DataCove /
Fraunhofer IOSB (project API4INSPIRE).

Why "drift anchor", not a live source
-------------------------------------
OPEN_QUESTIONS.md Q6 shipped Land Steiermark *disabled by default* because no
clean real-time feed was known. A 2026-06-19 read-only investigation refined
that: a machine-readable, hourly-structured, coordinate-tagged SensorThings feed
*does* exist and carries Graz/Steiermark PM10 / PM2.5 / NO2 / O3 / SO2 / CO with
station coordinates — but it is **not a reliable near-real-time feed**:

- The canonical DataCove endpoint (``service.datacove.eu/AirThings/v1.1``) was
  returning ``503 Service Unavailable``.
- The endpoint documented on the DataCove page
  (``airquality-frost.docker01.ilt-dmz.iosb.fraunhofer.de/v1.1``) ``308``-
  redirects to a *different* host, dropping the request path — i.e. broken.
- Only the (undocumented) redirect target,
  ``airquality-frost.k8s.ilt-dmz.iosb.fraunhofer.de/v1.1``, actually serves data.
- Steiermark PM ingestion was **frozen ~9 days stale** (newest STA.06 PM
  observation 2026-06-10 vs. a 2026-06-19 probe), while other streams were
  current — so the data AirWatch most wants here lags by days.
- The dataset is polluted with frozen duplicate station entries (2024/2023).

So this is honestly a **slow reference / drift anchor**, not a live-trigger
source. It is shipped opt-in, marks itself :data:`CADENCE` ``drift_anchor``, and
**surfaces the observation timestamp + computed lag in every result**
(``expose, don't assert`` — the same discipline as the thresholds). A reading
older than ``max_age_hours`` (a generous, drift-anchor-scale window) yields
``OUT_OF_COVERAGE`` with the real lag in the message rather than a misleading
"current" number — so while the feed is stalled an opted-in source simply
reports no current data, never a stale value dressed as live.

Like ``open_meteo.py`` / ``sensor_community.py`` this module is HA-free with an
injectable transport, so parsing/selection are pure and unit-testable offline.
Run it directly::

    python -m custom_components.airwatch.sources.land_steiermark --lat 47.07 --lon 15.44
    python -m custom_components.airwatch.sources.land_steiermark --station STA.06.164
    # widen the staleness window to see the (lagged) drift-anchor value today:
    python -m custom_components.airwatch.sources.land_steiermark --lat 47.07 --max-age-hours 300
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
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

SOURCE_NAME = "land_steiermark"

#: This source is a slow reference, not a live trigger. Carried so the analytics
#: layer (and a future freshness-weighting) can tell it apart from hourly sources.
CADENCE = "drift_anchor"

#: Pollutants the official network exposes that map onto AirWatch's canonical
#: keys (mirrors the registry's land_steiermark attribution — everything but the
#: aggregate european_aqi index).
SUPPORTED_POLLUTANTS: tuple[str, ...] = (
    "pm2_5",
    "pm10",
    "nitrogen_dioxide",
    "ozone",
    "sulphur_dioxide",
    "carbon_monoxide",
)
#: Canonical key -> SensorThings ``ObservedProperty/name`` in the harvest.
_OBSERVED_PROPERTY: dict[str, str] = {
    "pm2_5": "PM2.5",
    "pm10": "PM10",
    "nitrogen_dioxide": "NO2",
    "ozone": "O3",
    "sulphur_dioxide": "SO2",
    "carbon_monoxide": "CO",
}

#: Styrian stations carry localIds prefixed with the Austrian Bundesland code for
#: Steiermark (``06``); ``09`` is Vienna, etc. Used to scope auto-discovery.
REGION_PREFIX = "STA.06"

#: Default SensorThings base URL. This is the *working* (redirect-target) mirror
#: as of 2026-06-19; the canonical DataCove host is documented in
#: :data:`ALTERNATE_BASES` but was down. Overridable so a future stable endpoint
#: needs no code change.
DEFAULT_BASE_URL = "https://airquality-frost.k8s.ilt-dmz.iosb.fraunhofer.de/v1.1"
#: Other known endpoints for the same harvest (their state on 2026-06-19 noted).
ALTERNATE_BASES: tuple[str, ...] = (
    "https://service.datacove.eu/AirThings/v1.1",  # canonical; was 503
    "https://airquality-frost.docker01.ilt-dmz.iosb.fraunhofer.de/v1.1",  # broken redirect
)

DEFAULT_MAX_DISTANCE_KM: float = 25.0
#: Drift-anchor staleness tolerance. Generous next to the hourly primary sources
#: (a slow reference may legitimately lag), but not so wide it silently accepts
#: week-old data: a reading older than this → OUT_OF_COVERAGE with the real lag.
DEFAULT_MAX_AGE_HOURS: int = 72
#: Cap on stations pulled during discovery (defensive against a huge response).
_DISCOVERY_TOP = 400

Transport = Callable[[str, float], "tuple[int, Any]"]
AsyncTransport = Callable[[str, float], Awaitable["tuple[int, Any]"]]


def _http_get_json(url: str, timeout: float) -> tuple[int, Any]:
    """Default synchronous transport built on the standard library."""
    req = urllib.request.Request(url, headers={"User-Agent": "AirWatch/0.1.0"})
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


# -- pure parsing / selection -----------------------------------------------


@dataclass(slots=True)
class StationObservation:
    """One station's latest reading per pollutant, after parsing the harvest.

    ``readings`` maps a canonical pollutant key to ``(value, phenomenon_end)``
    where ``phenomenon_end`` is the UTC close of the observation's averaging
    period. Values here are pre-validity-filter (the selector applies the fault
    + staleness rules); a station may carry readings for only some pollutants.
    """

    local_id: str | None
    name: str | None
    latitude: float | None
    longitude: float | None
    distance_km: float | None
    readings: dict[str, tuple[float, datetime]] = field(default_factory=dict)


def _coerce_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _valid_value(value: float | None) -> float | None:
    """Validity filter: keep only finite, strictly-positive readings.

    Mirrors the proven ``0 < v`` discipline from the live Sensor.Community
    reader; in this official dataset an exact ``0.0`` denotes a missing /
    below-reporting value, not clean air, so it is rejected. (No SDS011-specific
    upper fault ceiling — these are QA'd reference instruments.)
    """
    if value is None:
        return None
    return value if value > 0 else None


def _parse_phenomenon_end(phenomenon_time: Any) -> datetime | None:
    """Parse a SensorThings ``phenomenonTime`` to the UTC end of its period.

    Accepts an instant (``2026-06-10T07:00:00Z``) or an interval
    (``start/end``); for an interval the end bound is used (when the averaging
    period closed). Returns an aware UTC datetime, or ``None`` if unparseable.
    """
    if not isinstance(phenomenon_time, str) or not phenomenon_time:
        return None
    instant = phenomenon_time.split("/")[-1].strip()
    iso = instant.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _latest_observation(datastream: dict) -> tuple[float, datetime] | None:
    """Extract ``(value, phenomenon_end)`` from a datastream's latest Observation."""
    observations = datastream.get("Observations") or []
    if not observations or not isinstance(observations[0], dict):
        return None
    obs = observations[0]
    value = _coerce_float(obs.get("result"))
    end = _parse_phenomenon_end(obs.get("phenomenonTime"))
    if value is None or end is None:
        return None
    return value, end


def _point_lat_lon(location_payload: Any) -> tuple[float | None, float | None]:
    """Pull (lat, lon) out of a SensorThings Location's GeoJSON Point."""
    if not isinstance(location_payload, dict):
        return None, None
    # The Location entity nests the GeoJSON under "location"; accept a bare
    # geometry too for robustness.
    geometry = location_payload.get("location", location_payload)
    if not isinstance(geometry, dict):
        return None, None
    coords = geometry.get("coordinates")
    if isinstance(coords, list) and len(coords) >= 2:
        lon = _coerce_float(coords[0])
        lat = _coerce_float(coords[1])
        return lat, lon
    return None, None


def _observed_property_to_key(name: Any) -> str | None:
    """Map a harvest ObservedProperty name back to a canonical pollutant key."""
    for key, op_name in _OBSERVED_PROPERTY.items():
        if op_name == name:
            return key
    return None


def _accumulate_station(
    acc: dict[str, StationObservation],
    *,
    local_id: str | None,
    name: str | None,
    lat: float | None,
    lon: float | None,
    requested_lat: float,
    requested_lon: float,
    pollutant: str | None,
    observation: tuple[float, datetime] | None,
) -> None:
    """Fold one (station, pollutant, latest-observation) row into the accumulator."""
    if local_id is None:
        return
    station = acc.get(local_id)
    if station is None:
        distance = (
            _haversine_km(requested_lat, requested_lon, lat, lon)
            if lat is not None and lon is not None
            else None
        )
        station = StationObservation(
            local_id=local_id,
            name=name,
            latitude=lat,
            longitude=lon,
            distance_km=distance,
        )
        acc[local_id] = station
    if pollutant is not None and observation is not None:
        prev = station.readings.get(pollutant)
        # Keep the most recent observation if a pollutant appears twice
        # (duplicate datastreams exist in the harvest).
        if prev is None or observation[1] > prev[1]:
            station.readings[pollutant] = observation


def parse_discovery(
    payload: Any,
    pollutants: Iterable[str],
    *,
    requested_lat: float,
    requested_lon: float,
) -> list[StationObservation]:
    """Parse a Datastreams-rooted discovery response into per-station readings.

    Each value row carries an expanded ``Thing`` (name + properties + Locations),
    ``ObservedProperty`` and the latest ``Observations``. Pure.
    """
    wanted = set(pollutants)
    values = payload.get("value", []) if isinstance(payload, dict) else []
    acc: dict[str, StationObservation] = {}
    for datastream in values:
        if not isinstance(datastream, dict):
            continue
        thing = datastream.get("Thing") or {}
        props = thing.get("properties") or {}
        local_id = props.get("localId")
        locations = thing.get("Locations") or []
        lat, lon = _point_lat_lon(locations[0]) if locations else (None, None)
        op_name = (datastream.get("ObservedProperty") or {}).get("name")
        key = _observed_property_to_key(op_name)
        observation = _latest_observation(datastream)
        _accumulate_station(
            acc,
            local_id=local_id,
            name=thing.get("name"),
            lat=lat,
            lon=lon,
            requested_lat=requested_lat,
            requested_lon=requested_lon,
            pollutant=key if key in wanted else None,
            observation=observation if key in wanted else None,
        )
    return list(acc.values())


def parse_things(
    payload: Any,
    pollutants: Iterable[str],
    *,
    requested_lat: float,
    requested_lon: float,
) -> list[StationObservation]:
    """Parse a Things-rooted (explicit-station) response into per-station readings.

    Each Thing carries expanded ``Locations`` and ``Datastreams`` (each with its
    ObservedProperty + latest Observations). Pure.
    """
    wanted = set(pollutants)
    values = payload.get("value", []) if isinstance(payload, dict) else []
    acc: dict[str, StationObservation] = {}
    for thing in values:
        if not isinstance(thing, dict):
            continue
        props = thing.get("properties") or {}
        local_id = props.get("localId")
        locations = thing.get("Locations") or []
        lat, lon = _point_lat_lon(locations[0]) if locations else (None, None)
        # Register the station even if no datastream matches (so the caller can
        # report "station found, no usable pollutant").
        _accumulate_station(
            acc,
            local_id=local_id,
            name=thing.get("name"),
            lat=lat,
            lon=lon,
            requested_lat=requested_lat,
            requested_lon=requested_lon,
            pollutant=None,
            observation=None,
        )
        for datastream in thing.get("Datastreams") or []:
            if not isinstance(datastream, dict):
                continue
            op_name = (datastream.get("ObservedProperty") or {}).get("name")
            key = _observed_property_to_key(op_name)
            if key not in wanted:
                continue
            _accumulate_station(
                acc,
                local_id=local_id,
                name=thing.get("name"),
                lat=lat,
                lon=lon,
                requested_lat=requested_lat,
                requested_lon=requested_lon,
                pollutant=key,
                observation=_latest_observation(datastream),
            )
    return list(acc.values())


def _fresh_valid_readings(
    station: StationObservation, now: datetime, max_age_hours: int
) -> dict[str, tuple[float, datetime]]:
    """The station's readings that pass the validity + staleness filters."""
    out: dict[str, tuple[float, datetime]] = {}
    for pollutant, (value, end) in station.readings.items():
        if _valid_value(value) is None:
            continue
        age_h = (now - end).total_seconds() / 3600.0
        if 0 <= age_h <= max_age_hours:
            out[pollutant] = (value, end)
    return out


def select_station(
    stations: list[StationObservation],
    *,
    max_distance_km: float,
    now: datetime,
    max_age_hours: int,
    explicit: bool,
) -> StationObservation | None:
    """Pick the station to report: nearest *usable* in range, or the only one.

    For discovery, candidates must have coordinates and lie within
    ``max_distance_km``. The nearest station that actually carries a fresh, valid
    reading wins — a closer station with only stale or missing (0/None) data must
    not shadow a slightly-farther usable one. If none are usable the nearest
    in-range station is returned anyway so the caller can explain *why* it was
    unusable. For an explicit station the single returned station is used as-is.
    """
    if explicit:
        return stations[0] if stations else None
    in_range = [
        s
        for s in stations
        if s.distance_km is not None and s.distance_km <= max_distance_km
    ]
    if not in_range:
        return None
    usable = [s for s in in_range if _fresh_valid_readings(s, now, max_age_hours)]
    # Fallback (nothing fresh) prefers a station carrying *some* valid reading so
    # the caller's diagnostic can surface the real feed lag, not just "no data".
    any_valid = [
        s
        for s in in_range
        if any(_valid_value(v) is not None for v, _e in s.readings.values())
    ]
    pool = usable or any_valid or in_range
    pool.sort(key=lambda s: (s.distance_km, -len(s.readings)))
    return pool[0]


def build_result(
    station: StationObservation | None,
    pollutants: Iterable[str],
    *,
    requested_lat: float,
    requested_lon: float,
    now: datetime,
    max_age_hours: int,
) -> SourceResult:
    """Turn the selected station into a drift-anchor SourceResult.

    OK when the station has at least one fresh, valid reading — each pollutant's
    series surfaces the station + observation time + computed lag in ``native``
    (``expose, don't assert``). OUT_OF_COVERAGE otherwise, with a message that
    states *why* (no station in range, or the nearest station's data is stale by
    N days) rather than emitting a misleading value.
    """
    now_iso = now.isoformat(timespec="seconds")
    pollutant_set = list(pollutants)

    if station is None:
        return SourceResult(
            source=SOURCE_NAME,
            status=SourceStatus.OUT_OF_COVERAGE,
            requested_lat=requested_lat,
            requested_lon=requested_lon,
            generated_at=now_iso,
            message="No Land Steiermark station within range of this location.",
        )

    fresh = _fresh_valid_readings(station, now, max_age_hours)
    label = station.name or station.local_id or "unknown"
    dist = (
        f"{station.distance_km:.1f} km"
        if station.distance_km is not None
        else "distance unknown"
    )

    if not fresh:
        # Distinguish the two reasons emptiness can arise: all readings invalid
        # (0 / missing) vs. valid-but-stale (the feed lag we expect here).
        valid_ends = [
            end
            for _p, (value, end) in station.readings.items()
            if _valid_value(value) is not None
        ]
        if not station.readings:
            why = "station returned no readings"
        elif not valid_ends:
            why = "station reports no valid (positive) readings"
        else:
            newest = max(valid_ends)
            lag_d = (now - newest).total_seconds() / 86400.0
            why = (
                f"newest valid reading {newest.isoformat()} is ~{lag_d:.1f} days "
                f"old (feed lag); exceeds the {max_age_hours}h drift-anchor window"
            )
        return SourceResult(
            source=SOURCE_NAME,
            status=SourceStatus.OUT_OF_COVERAGE,
            requested_lat=requested_lat,
            requested_lon=requested_lon,
            snapped_lat=station.latitude,
            snapped_lon=station.longitude,
            generated_at=now_iso,
            station=f"{label} ({station.local_id}) · {dist}",
            message=f"Nearest Land Steiermark station {label}: {why}.",
        )

    series: dict[str, PollutantSeries] = {}
    newest_end = max(end for _v, end in fresh.values())
    for pollutant in pollutant_set:
        reading = fresh.get(pollutant)
        if reading is None:
            continue
        value, end = reading
        lag_d = (now - end).total_seconds() / 86400.0
        series[pollutant] = PollutantSeries(
            pollutant=pollutant,
            unit="µg/m³",
            current=round(value, 1),
            values=[round(value, 1)],
            # Drift-anchor provenance: which station, when, and how stale.
            native=f"{station.local_id} @ {end.isoformat()} (≈{lag_d:.1f} d old)",
        )

    newest_iso = newest_end.isoformat(timespec="seconds")
    lag_days = (now - newest_end).total_seconds() / 86400.0
    return SourceResult(
        source=SOURCE_NAME,
        status=SourceStatus.OK,
        requested_lat=requested_lat,
        requested_lon=requested_lon,
        snapped_lat=station.latitude,
        snapped_lon=station.longitude,
        times=[newest_iso],
        current_time=newest_iso,
        pollutants=series,
        generated_at=now_iso,
        station=(
            f"{label} ({station.local_id}) · {dist} · drift anchor, "
            f"newest {newest_iso} (≈{lag_days:.1f} d old)"
        ),
    )


# -- source client ----------------------------------------------------------


class LandSteiermarkSource:
    """Official Steiermark stations via the Austrian SensorThings harvest.

    Drift-anchor (slow reference) source — see the module docstring. With an
    explicit ``station`` localId it queries that station directly; otherwise it
    discovers Steiermark stations near the location and reports the nearest in
    range. Disabled by default (OPEN_QUESTIONS.md Q6); HA-free with an injectable
    transport so parsing is unit-testable offline.
    """

    name = SOURCE_NAME
    cadence = CADENCE
    # Drift anchor: no own history series and not recorder-baselined in v1 (it
    # contributes a level to consensus, not a percentile).
    supports_history = False
    provides_history_series = False

    def __init__(
        self,
        latitude: float,
        longitude: float,
        pollutants: Iterable[str] | None = None,
        *,
        station: str | None = None,
        max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
        max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        retry_delay: float = 1.0,
        transport: Transport | None = None,
        async_transport: AsyncTransport | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.latitude = float(latitude)
        self.longitude = float(longitude)
        self.pollutants = self._validate_pollutants(pollutants)
        self.station = (station or "").strip() or None
        self.max_distance_km = float(max_distance_km)
        self.max_age_hours = max(1, int(max_age_hours))
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry_delay = retry_delay
        self._transport: Transport = transport or _http_get_json
        self._async_transport: AsyncTransport | None = async_transport
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    @staticmethod
    def _validate_pollutants(pollutants: Iterable[str] | None) -> list[str]:
        if pollutants is None:
            return list(SUPPORTED_POLLUTANTS)
        return [p for p in pollutants if p in _OBSERVED_PROPERTY]

    # -- query building ------------------------------------------------------

    def _op_filter(self) -> str:
        names = [_OBSERVED_PROPERTY[p] for p in self.pollutants]
        return " or ".join(f"ObservedProperty/name eq '{n}'" for n in names)

    @staticmethod
    def _query(params: list[tuple[str, str]]) -> str:
        # Keep the literal ``$key`` names, percent-encode only the values — the
        # FROST server accepts this (mirrors curl --data-urlencode).
        return "&".join(
            f"{k}={urllib.parse.quote(v, safe='')}" for k, v in params
        )

    def discovery_url(self) -> str:
        op = self._op_filter()
        expand = (
            "Thing($select=name,properties;$expand=Locations($select=location)),"
            "ObservedProperty($select=name),"
            "Observations($orderby=phenomenonTime desc;$top=1;"
            "$select=phenomenonTime,result)"
        )
        params = [
            ("$filter", f"startswith(Thing/properties/localId,'{REGION_PREFIX}') and ({op})"),
            ("$expand", expand),
            ("$select", "@iot.id"),
            ("$top", str(_DISCOVERY_TOP)),
        ]
        return f"{self.base_url}/Datastreams?{self._query(params)}"

    def station_url(self, local_id: str) -> str:
        op = self._op_filter()
        expand = (
            "Locations($select=location),"
            f"Datastreams($filter={op};"
            "$expand=ObservedProperty($select=name),"
            "Observations($orderby=phenomenonTime desc;$top=1;"
            "$select=phenomenonTime,result))"
        )
        params = [
            ("$filter", f"properties/localId eq '{local_id}'"),
            ("$expand", expand),
            ("$select", "name,properties"),
        ]
        return f"{self.base_url}/Things?{self._query(params)}"

    # -- fetching ------------------------------------------------------------

    def fetch(self) -> SourceResult:
        """Synchronous fetch (standalone entry point + tests)."""
        if not self.pollutants:
            return self._empty_result("No supported pollutants selected.")
        payload = self._get_sync(self._request_url())
        return self._build(payload)

    async def async_fetch(
        self, session: aiohttp.ClientSession | None = None
    ) -> SourceResult:
        """Async fetch for Home Assistant. Mirrors :meth:`fetch`."""
        if not self.pollutants:
            return self._empty_result("No supported pollutants selected.")
        if self._async_transport is not None:
            payload = await self._get_async(self._async_transport, self._request_url())
            return self._build(payload)

        import aiohttp

        owns_session = session is None
        if owns_session:
            session = aiohttp.ClientSession()
        try:
            transport = self._make_aiohttp_transport(aiohttp, session)
            payload = await self._get_async(transport, self._request_url())
            return self._build(payload)
        finally:
            if owns_session:
                await session.close()

    def _request_url(self) -> str:
        return self.station_url(self.station) if self.station else self.discovery_url()

    def _build(self, payload: Any) -> SourceResult:
        now = self._now_fn()
        if self.station:
            stations = parse_things(
                payload,
                self.pollutants,
                requested_lat=self.latitude,
                requested_lon=self.longitude,
            )
        else:
            stations = parse_discovery(
                payload,
                self.pollutants,
                requested_lat=self.latitude,
                requested_lon=self.longitude,
            )
        chosen = select_station(
            stations,
            max_distance_km=self.max_distance_km,
            now=now,
            max_age_hours=self.max_age_hours,
            explicit=bool(self.station),
        )
        return build_result(
            chosen,
            self.pollutants,
            requested_lat=self.latitude,
            requested_lon=self.longitude,
            now=now,
            max_age_hours=self.max_age_hours,
        )

    def _empty_result(self, message: str) -> SourceResult:
        return SourceResult(
            source=SOURCE_NAME,
            status=SourceStatus.OUT_OF_COVERAGE,
            requested_lat=self.latitude,
            requested_lon=self.longitude,
            generated_at=self._now_fn().isoformat(timespec="seconds"),
            message=message,
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
                    f"Land Steiermark request failed after {attempts} attempts: {err}"
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
                    f"Land Steiermark request failed after {attempts} attempts: {err}"
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


# -- standalone entry point --------------------------------------------------


def _summarise(result: SourceResult) -> str:
    lines = [f"AirWatch · Land Steiermark — status: {result.status.value}"]
    lines.append(f"  requested: {result.requested_lat:.4f}, {result.requested_lon:.4f}")
    if result.station:
        lines.append(f"  station:   {result.station}")
    if result.status is not SourceStatus.OK:
        if result.message:
            lines.append(f"  message:   {result.message}")
        return "\n".join(lines)
    lines.append(f"  time:      {result.current_time}")
    lines.append("")
    lines.append(f"  {'pollutant':<18} {'value':>8}  unit   provenance")
    lines.append(f"  {'-' * 18} {'-' * 8}  {'-' * 5}  {'-' * 10}")
    for key, series in result.pollutants.items():
        cur = "n/a" if series.current is None else f"{series.current:.1f}"
        lines.append(f"  {key:<18} {cur:>8}  {series.unit}  {series.native}")
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe Land Steiermark (Austrian SensorThings) for a location or station.",
    )
    parser.add_argument("--lat", type=float, default=47.0707, help="latitude")
    parser.add_argument("--lon", type=float, default=15.4395, help="longitude")
    parser.add_argument(
        "--station", default="", help="explicit station localId (e.g. STA.06.164)"
    )
    parser.add_argument("--max-distance-km", type=float, default=DEFAULT_MAX_DISTANCE_KM)
    parser.add_argument("--max-age-hours", type=int, default=DEFAULT_MAX_AGE_HOURS)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args(argv)

    source = LandSteiermarkSource(
        args.lat,
        args.lon,
        station=args.station or None,
        max_distance_km=args.max_distance_km,
        max_age_hours=args.max_age_hours,
        base_url=args.base_url,
    )
    print(f"GET {source._request_url()}\n")
    result = source.fetch()
    print(_summarise(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
