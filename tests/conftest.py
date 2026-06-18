"""Pytest configuration for AirWatch tests.

Ensures the repository root is importable so ``custom_components.airwatch``
resolves regardless of pytest's import mode, and enables Home Assistant to load
the custom integration during HA-based tests.
"""

from __future__ import annotations

import os
import sys

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow HA to discover and load custom_components/airwatch in tests."""
    yield


@pytest.fixture(autouse=True, scope="session")
def _warm_aiohttp_resolver_thread():
    """Pre-spawn aiohttp's internal shutdown-watcher thread once per session.

    Constructing an ``aiohttp.ClientSession`` (which the ``aioclient_mock``
    fixture does to build its mocked session) eagerly spawns a long-lived
    ``Thread-N (_run_safe_shutdown_loop)`` daemon that never exits for the
    process lifetime. pHACC's per-test ``verify_cleanup`` snapshots the live
    threads at test start and fails on any new non-dummy thread at teardown —
    so whichever HTTP-using test happens to create the first session would be
    flagged for a leak it didn't cause. Warming the thread here, before any
    test's snapshot, means it is always part of ``threads_before`` and never
    mis-attributed to a test. No HA, no event loop, no network.
    """
    import asyncio

    from aiohttp import ClientSession

    async def _warm() -> None:
        session = ClientSession()
        await session.close()

    asyncio.run(_warm())
    yield
