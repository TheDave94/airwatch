"""AirWatch — PRIMARY source: Open-Meteo / CAMS air-quality.

Endpoint: https://air-quality-api.open-meteo.com/v1/air-quality  (free, keyless,
hourly, EU-wide µg/m³, 92-day backfill + 5-day forecast). SAME host PollenWatch
already uses — swap pollen params for air-quality params.

TODO: adapt from pollenwatch/sources/open_meteo.py. Change hourly= params to
pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide,european_aqi.
Coverage probe (HTTP 400 "No data") + grid-snap handling port ~as-is.
See OPEN_QUESTIONS.md for the exact param list.
"""
