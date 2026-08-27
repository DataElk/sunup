"""The browser live-site pipeline must agree with the Python WBGT pipeline."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess

import pytest

from acclimate import wbgt
from acclimate.sources import openmeteo
from acclimate.sources.fixtures import FixtureStore
from acclimate.sources.fortyguard import parse_temperature_grid

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


@pytest.fixture(scope="module")
def replay():
    result = subprocess.run(
        ["node", os.path.join("tests", "replay_environment.mjs")],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_third_party_hourly_inputs_and_fortyguard_cell_match_python(replay):
    fixtures = FixtureStore()
    grid = parse_temperature_grid(
        fixtures.load("heatmap/phoenix_singleday_filter3_raw.json"))
    regional = openmeteo.load_day(
        33.4484, -112.0740, dt.date(2024, 7, 15), fixtures)
    expected = wbgt.build_wbgt_day(
        site_id="browser_contract",
        grid=grid,
        env=None,
        site_longitude=-112.0740,
        site_latitude=33.4484,
        open_meteo=regional,
    )
    selected = grid.cell_at(-112.0740, 33.4484)
    assert replay["cell"]["min"] == pytest.approx(selected.min_c, abs=1e-9)
    assert replay["cell"]["mean"] == pytest.approx(selected.mean_c, abs=1e-9)
    assert replay["cell"]["max"] == pytest.approx(selected.max_c, abs=1e-9)
    assert replay["series"] == pytest.approx(expected.series_c, abs=2e-6)


def test_polygon_uses_interior_median_and_discards_edge_cells(replay):
    cell = replay["boundaryCell"]
    assert cell["cellsUsed"] == 2
    assert cell["min"] == pytest.approx(15.0)
    assert cell["mean"] == pytest.approx(20.0)
    assert cell["max"] == pytest.approx(25.0)


def test_live_site_weather_is_not_derived_from_a_seed_curve():
    with open(os.path.join(ROOT, "app", "js", "siteweather.js"),
              encoding="utf-8") as handle:
        source = handle.read()
    assert "baseSeries" not in source
    assert "hot_site" not in source
    assert "cool_site" not in source
    assert "buildWbgtSeries" in source
    assert "bufferedAoi" in source
