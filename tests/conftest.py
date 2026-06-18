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
