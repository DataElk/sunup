"""Test wiring. No network is available to these tests, by design."""

from __future__ import annotations

import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(REPO_ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


@pytest.fixture(scope="session")
def store():
    from sunup.sources.fixtures import FixtureStore

    return FixtureStore()


@pytest.fixture(scope="session")
def reference_day():
    from sunup import reference

    return reference.build()


@pytest.fixture(scope="session")
def reference_inputs(store):
    from sunup import reference

    return reference.load_inputs(store=store)
