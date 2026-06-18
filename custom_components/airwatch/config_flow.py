"""AirWatch — ConfigFlow (location + pollutant selection + coverage probe)
and OptionsFlow (update interval, per-source enablement/keys, card layout).

TODO: port from pollenwatch/.../config_flow.py. Adapt: species multiselect ->
pollutant multiselect; region preselection via region_defaults; coverage probe
stays Open-Meteo HTTP-400 detection. Storage split (data=location,
options=everything) unchanged.
"""
