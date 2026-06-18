"""AirWatch — SECONDARY source: Land Steiermark official stations (Graz).

Daily-mean only (TMW) as cleanly accessible — a slow drift/reference anchor, NOT a
live feed (data.gv.at CKAN API is dead; live HMW is portal-only). Lower update
cadence; flagged low-freshness so fusion/consensus weights it accordingly.

TODO: NEW source. Decide access path (parse portal vs annual archive). May ship
disabled-by-default. Reuse base.py Protocol.
"""
