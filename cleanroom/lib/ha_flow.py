"""Config-flow + options-flow over REST.

The pollutant-field name AND flow shape track the installed airwatch VERSION.
AirWatch's v1 config-flow (VERSION 1) is a SINGLE-step `user` form:

    submit {location, selected_pollutants, update_interval} → create_entry

The ``pollutant_field`` (e.g. ``selected_pollutants``) and ``flow_version`` are
looked up from cleanroom/config/pinned_release.json and passed in, so a future
schema bump (a renamed field or a multi-step flow) is a config edit, not a code
change. The two-step branch is carried defensively for any future VERSION that
splits location and pollutant selection into separate steps (mirrors the shape
PollenWatch's v3 flow used).
"""
from __future__ import annotations

from typing import Any

from .ha_api import HAClient


def create_airwatch_entry(
    client: HAClient,
    *,
    latitude: float,
    longitude: float,
    pollutants: list[str],
    pollutant_field: str,
    flow_version: int,
    update_interval: int = 60,
) -> str | None:
    """Walk the airwatch config-flow. Returns the new entry_id, or None on failure.

    Branches on `flow_version`: single-step for v1, two-step for any future v2+."""
    st, init = client.request(
        "/api/config/config_entries/flow",
        method="POST",
        data={"handler": "airwatch", "show_advanced_options": False},
    )
    if st != 200 or not isinstance(init, dict) or init.get("type") != "form":
        print(f"  ! config_flow init failed: HTTP {st}: {init}")
        return None
    flow_id = init["flow_id"]

    if flow_version <= 1:
        # Single-step (v1): submit location + pollutants + interval together.
        submit = {
            "location": {"latitude": latitude, "longitude": longitude},
            pollutant_field: pollutants,
            "update_interval": update_interval,
        }
        st, result = client.request(
            f"/api/config/config_entries/flow/{flow_id}",
            method="POST", data=submit, timeout=60,
        )
        if isinstance(result, dict) and result.get("type") == "create_entry":
            return result["result"]["entry_id"]
        print(f"  ! config_flow (v1) did not create entry: HTTP {st}: {result}")
        return None

    # Two-step (future v2+): submit location only, then submit pollutants.
    st, step1 = client.request(
        f"/api/config/config_entries/flow/{flow_id}",
        method="POST",
        data={"location": {"latitude": latitude, "longitude": longitude}},
        timeout=60,
    )
    if not isinstance(step1, dict):
        print(f"  ! step 'user' returned non-dict: HTTP {st}: {step1}")
        return None
    if step1.get("type") == "create_entry":
        # Some schemas may complete in one step; tolerate it.
        return step1["result"]["entry_id"]
    if step1.get("type") != "form" or step1.get("step_id") != "pollutants":
        print(f"  ! step 'user' did not advance to 'pollutants': HTTP {st}: {step1}")
        return None

    st, step2 = client.request(
        f"/api/config/config_entries/flow/{flow_id}",
        method="POST",
        data={pollutant_field: pollutants, "update_interval": update_interval},
        timeout=60,
    )
    if isinstance(step2, dict) and step2.get("type") == "create_entry":
        return step2["result"]["entry_id"]
    print(f"  ! step 'pollutants' did not create entry: HTTP {st}: {step2}")
    return None


def submit_airwatch_options(
    client: HAClient,
    entry_id: str,
    *,
    pollutants: list[str],
    pollutant_field: str,
    options: dict[str, Any],
    update_interval: int = 60,
) -> bool:
    """Walk the airwatch options-flow for an existing entry. Returns True on
    create_entry.

    AirWatch v1 options edit pollutants + update_interval; the per-source
    enablement (CONF_SOURCES) is seeded at setup and preserved by the options
    flow, so the harness does not resubmit it. `options` is accepted for forward
    compatibility (a future source-toggle options step)."""
    st, init = client.request(
        "/api/config/config_entries/options/flow",
        method="POST",
        data={"handler": entry_id},
    )
    if st != 200 or not isinstance(init, dict) or init.get("type") != "form":
        print(f"  ! options_flow init failed: HTTP {st}: {init}")
        return False
    flow_id = init["flow_id"]

    submit: dict[str, Any] = {
        pollutant_field: pollutants,
        "update_interval": update_interval,
    }

    st, result = client.request(
        f"/api/config/config_entries/options/flow/{flow_id}",
        method="POST",
        data=submit,
        timeout=60,
    )
    if isinstance(result, dict) and result.get("type") == "create_entry":
        return True
    print(f"  ! options_flow submit did not create entry: HTTP {st}: {result}")
    return False
