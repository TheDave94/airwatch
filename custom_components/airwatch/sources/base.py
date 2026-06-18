"""AirWatch — source abstraction: AirQualitySource Protocol, SourceResult /
PollutantSeries dataclasses, exception hierarchy (SourceError, SourceUnavailable,
SourceResponseError, SourceAuthError).

TODO: port from pollenwatch/sources/base.py ~AS-IS (rename PollenSource ->
AirQualitySource, AllergenSeries -> PollutantSeries). Protocol + dataclasses are
domain-agnostic.
"""
