"""M0 exit test.

SPEC.md, milestone M0:

    Typed client over the endpoints in FORTYGUARD_API_CONTRACT.md. Disk cache
    keyed on a hash of the full request payload. REFRESH flag defaults to False.

    Exit: with the network disconnected, every fixture request returns from
    cache. Clamping is applied to exceedance values on ingest. A negative or
    over-window value cannot reach the rest of the system.

"Network disconnected" is enforced here by installing OfflineTransport, which
raises on any call, and by asserting the transport recorded zero calls.
"""

from __future__ import annotations

import json
import os
import re

import pytest

from acclimate import constants as C
from acclimate.errors import (
    ActivityFailed,
    ImplausibleValue,
    LiveCallBlocked,
    PollTimeout,
)
from acclimate.sources import seed
from acclimate.sources.cache import DiskCache, cache_key, canonical
from acclimate.sources.client import FortyGuardClient, build_heatmap_payload
from acclimate.sources.fixtures import FixtureStore
from acclimate.sources.fortyguard import (
    clamp_exceedance_hours,
    parse_analysis_grid,
    parse_env_params,
    parse_temperature_grid,
)
from acclimate.sources.transport import (
    OfflineTransport,
    RecordingTransport,
    Transport,
)


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    """A cache seeded from the committed fixtures, in a throwaway directory."""
    cache = DiskCache(str(tmp_path_factory.mktemp("cache")))
    result = seed.seed_cache(cache=cache, store=FixtureStore())
    assert result.ok, "fixtures declared in INDEX.json are missing: %s" % result.missing_files
    assert result.seeded, "nothing was seeded"
    return cache, result


# ---------------------------------------------------------------------------
# The exit criteria
# ---------------------------------------------------------------------------


def test_every_indexed_fixture_request_serves_from_cache(seeded):
    """THE M0 EXIT TEST. Network disconnected; every fixture request resolves."""
    cache, _ = seeded
    store = FixtureStore()
    transport = RecordingTransport(OfflineTransport())
    client = FortyGuardClient(cache=cache, transport=transport, refresh=False)

    replayed = 0
    for entry in seed.load_index(store):
        if entry.get("role") == "derived":
            continue
        if entry["method"] == "create_heatmap":
            response = client.create_heatmap(**entry["kwargs"])
            assert response, entry["file"]
        elif entry["method"] == "environmental_parameters":
            response = client.environmental_parameters(**entry["kwargs"])
            assert response.result["locations"], entry["file"]
        replayed += 1

    assert replayed >= 8, replayed
    assert transport.call_count == 0, (
        "the transport was reached %d times — the cache did not cover every "
        "fixture request" % transport.call_count
    )
    assert client.live_calls == 0
    assert client.cache_hits == replayed


def test_a_request_with_no_fixture_is_blocked_not_silently_wrong(seeded):
    """A cache miss must fail loudly, naming the call — never invent a response."""
    cache, _ = seeded
    client = FortyGuardClient(cache=cache, transport=OfflineTransport())
    with pytest.raises(LiveCallBlocked) as excinfo:
        client.create_heatmap(
            polygon_aoi={"type": "FeatureCollection", "features": []},
            start_date="1999-01-01",
            filter_type=3,
        )
    assert "1999-01-01" in str(excinfo.value)


def test_refresh_defaults_to_false():
    """SPEC.md M0 and contract section 10 both require this default."""
    client = FortyGuardClient()
    assert client.refresh is False
    assert isinstance(client.transport, OfflineTransport)


def test_refresh_true_bypasses_the_cache_and_is_therefore_blocked_offline(seeded):
    cache, _ = seeded
    store = FixtureStore()
    entry = next(e for e in seed.load_index(store)
                 if e.get("role") != "derived" and e["method"] == "create_heatmap")
    client = FortyGuardClient(cache=cache, transport=OfflineTransport(), refresh=True)
    with pytest.raises(LiveCallBlocked):
        client.create_heatmap(**entry["kwargs"])


# ---------------------------------------------------------------------------
# Clamping — "a negative or over-window value cannot reach the rest of the system"
# ---------------------------------------------------------------------------


def _analysis_payload(values, window=168.0):
    ring = [[0.0, 0.0], [0.001, 0.0], [0.001, 0.001], [0.0, 0.001]]
    return {
        "result": {
            "map_data": {
                "features": [
                    {"properties": {"tile_id": i, "value": v},
                     "geometry": {"type": "Polygon", "coordinates": [ring]}}
                    for i, v in enumerate(values)
                ]
            },
            "stats_data": {"analytic_type": "exceedance", "units": "hour",
                           "min": min(values), "max": max(values),
                           "mean": sum(values) / len(values)},
        }
    }


def test_clamp_handles_the_two_measured_pathologies():
    """Contract section 5 records both of these from real responses."""
    assert clamp_exceedance_hours(-0.3176, 168.0) == 0.0
    assert clamp_exceedance_hours(168.62, 168.0) == 168.0
    assert clamp_exceedance_hours(52.3, 168.0) == 52.3


def test_no_impossible_duration_survives_ingest():
    grid = parse_analysis_grid(_analysis_payload([-0.3176, 168.62, 52.3, 0.0, 168.0]), 168.0)
    for value in grid.values():
        assert 0.0 <= value <= 168.0
    assert min(grid.values()) >= C.EXCEEDANCE_CLAMP_MIN_H
    assert grid.clamped_low == 1
    assert grid.clamped_high == 1
    assert grid.clamped_total == 2


def test_raw_values_are_kept_so_the_clamp_is_auditable():
    grid = parse_analysis_grid(_analysis_payload([-0.3176, 52.3]), 168.0)
    negative = grid.cells[0]
    assert negative.raw_value == pytest.approx(-0.3176)
    assert negative.value == 0.0
    assert negative.was_clamped
    assert not grid.cells[1].was_clamped


def test_clamped_fraction_is_reported_not_swallowed():
    """A grid where many cells clamp means a badly chosen threshold — that has
    to be visible to whoever ranks sites (contract section 5)."""
    grid = parse_analysis_grid(_analysis_payload([-1.0, -2.0, -0.5, 10.0]), 168.0)
    assert grid.clamped_fraction == pytest.approx(0.75)


def test_wildly_out_of_range_values_raise_instead_of_clamping():
    """A value far outside the window is a wrong window length or wrong units,
    not interpolation noise. Clamping it would hide a real bug."""
    with pytest.raises(ImplausibleValue):
        parse_analysis_grid(_analysis_payload([5000.0]), 168.0)
    with pytest.raises(ImplausibleValue):
        parse_analysis_grid(_analysis_payload([-500.0]), 168.0)


def test_analysis_grid_rejects_a_tcm_payload():
    payload = {"result": {"map_data": {"features": [
        {"properties": {"tile_id": 0, "average_temperature": 39.7},
         "geometry": {"coordinates": [[[0, 0], [1, 0], [1, 1]]]}}]}}}
    with pytest.raises(ValueError) as excinfo:
        parse_analysis_grid(payload, 168.0)
    assert "average/min/max_temperature" in str(excinfo.value)


def test_percentile_ranking_is_available_because_min_max_are_artifacts():
    """Contract section 5 mandates 5th/95th percentile ranking, because extremes
    cluster on the AOI boundary."""
    grid = parse_analysis_grid(_analysis_payload([float(v) for v in range(0, 101)]), 168.0)
    assert grid.percentile(0) == 0.0
    assert grid.percentile(100) == 100.0
    assert grid.percentile(50) == pytest.approx(50.0)
    assert grid.percentile(95) == pytest.approx(95.0)


def test_window_hours_must_be_supplied_and_positive():
    with pytest.raises(ValueError):
        parse_analysis_grid(_analysis_payload([1.0]), 0.0)


# ---------------------------------------------------------------------------
# Cache keying
# ---------------------------------------------------------------------------


def test_key_is_insensitive_to_key_order_but_sensitive_to_values():
    a = cache_key("/v1/heatmap", {"x": 1, "y": {"b": 2, "a": 3}})
    b = cache_key("/v1/heatmap", {"y": {"a": 3, "b": 2}, "x": 1})
    assert a == b
    assert cache_key("/v1/heatmap", {"x": 2}) != cache_key("/v1/heatmap", {"x": 1})
    assert cache_key("/v1/env_params", {"x": 1}) != cache_key("/v1/heatmap", {"x": 1})


def test_analysis_list_order_changes_the_key():
    """Deliberate. The API may or may not treat order as meaningful, and the
    cache must not claim two different requests are the same one."""
    base = dict(latitude=1.0, longitude=2.0, temperature=3.0, start_date="2024-07-15")
    from acclimate.sources.client import build_env_params_payload

    one = build_env_params_payload(analysis=["a", "b"], **base)
    two = build_env_params_payload(analysis=["b", "a"], **base)
    assert cache_key("/v1/env_params", one) != cache_key("/v1/env_params", two)


def test_canonical_is_stable_across_runs():
    assert canonical({"b": 1, "a": [3, 2]}) == '{"a":[3,2],"b":1}'


def test_seeding_is_idempotent(tmp_path):
    cache = DiskCache(str(tmp_path))
    first = seed.seed_cache(cache=cache)
    second = seed.seed_cache(cache=cache)
    assert first.seeded and not second.seeded
    assert len(second.already_present) == len(first.seeded)


def test_seeded_keys_match_what_the_client_will_ask_for(seeded):
    """The seeder and the client must derive keys through the same builders."""
    cache, result = seeded
    store = FixtureStore()
    for entry in seed.load_index(store):
        if entry.get("role") == "derived" or entry["method"] != "create_heatmap":
            continue
        payload = build_heatmap_payload(**entry["kwargs"])
        assert cache.has("/v1/heatmap", payload), entry["file"]


def test_derived_fixtures_are_not_cached_as_responses(seeded):
    """A summary must never be able to masquerade as an API response."""
    _cache, result = seeded
    assert "heatmap/phoenix_40c_exceedance_sites.json" in result.derived_skipped
    assert "heatmap/filter3_properties_2024-07-15.json" in result.derived_skipped


# ---------------------------------------------------------------------------
# Polling and envelopes
# ---------------------------------------------------------------------------


class FakeTransport(Transport):
    """Scripted responses, so polling can be tested without a clock or a socket."""

    def __init__(self, submit, statuses):
        self.submit_response = submit
        self.statuses = list(statuses)
        self.posts, self.gets = [], []

    def post(self, url, headers, payload):
        self.posts.append((url, payload))
        return self.submit_response

    def get(self, url, headers):
        self.gets.append(url)
        return self.statuses.pop(0) if self.statuses else {"data": {"status": "Processing"}}


def _completed(result):
    return {"data": {"activity_id": "abc", "status": "Completed", "result": result}}


@pytest.mark.parametrize("status", ["Completed", "completed", "SUCCEEDED", "Succeeded"])
def test_status_is_matched_case_insensitively(tmp_path, status):
    """Contract section 1 lists all of these as terminal success."""
    body = {"data": {"activity_id": "abc", "status": status, "result": {"map_data": {}}}}
    transport = FakeTransport({"data": {"activity_id": "abc"}}, [body])
    client = FortyGuardClient(cache=DiskCache(str(tmp_path)), transport=transport,
                              refresh=True, sleep=lambda _s: None)
    response = client.create_heatmap(polygon_aoi={}, start_date="2024-07-15", filter_type=3)
    assert response is body


def test_failed_status_raises(tmp_path):
    transport = FakeTransport({"data": {"activity_id": "abc"}},
                              [{"data": {"activity_id": "abc", "status": "Failed"}}])
    client = FortyGuardClient(cache=DiskCache(str(tmp_path)), transport=transport,
                              refresh=True, sleep=lambda _s: None)
    with pytest.raises(ActivityFailed):
        client.create_heatmap(polygon_aoi={}, start_date="2024-07-15", filter_type=3)


def test_poll_timeout_keeps_the_activity_id(tmp_path):
    """A submitted activity has already been paid for. The id must survive so it
    can be retrieved rather than resubmitted — the mistake made on 2026-08-24."""
    transport = FakeTransport({"data": {"activity_id": "70dcdf72"}}, [])
    client = FortyGuardClient(cache=DiskCache(str(tmp_path)), transport=transport,
                              refresh=True, sleep=lambda _s: None, poll_timeout_s=0.0)
    with pytest.raises(PollTimeout) as excinfo:
        client.create_heatmap(polygon_aoi={}, start_date="2024-07-15", filter_type=3)
    assert "70dcdf72" in str(excinfo.value)


def test_a_completed_response_is_written_to_cache(tmp_path):
    cache = DiskCache(str(tmp_path))
    body = _completed({"map_data": {"features": []}})
    transport = FakeTransport({"data": {"activity_id": "abc"}}, [body])
    client = FortyGuardClient(cache=cache, transport=transport, refresh=True,
                              sleep=lambda _s: None)
    client.create_heatmap(polygon_aoi={}, start_date="2024-07-15", filter_type=3)
    # A second, non-refreshing client must now serve it offline.
    offline = FortyGuardClient(cache=cache, transport=OfflineTransport())
    again = offline.create_heatmap(polygon_aoi={}, start_date="2024-07-15", filter_type=3)
    assert again == body
    assert offline.cache_hits == 1


# ---------------------------------------------------------------------------
# env_params cap tolerance — correct whether or not the cap binds
# ---------------------------------------------------------------------------


def _env_body(names):
    return _completed({
        "metadata": {"timestamps": ["2024-07-15T%02d:00:00-07:00" % h for h in range(24)],
                     "timezone_offset_hours": -7},
        "locations": [{"lat": 33.4484, "lon": -112.0740, "elevation": 333.0,
                       "temperature": 39.5,
                       "parameters": {n: [1.0] * 24 for n in names}}],
    })


class ChunkAwareTransport(Transport):
    """Simulates the endpoint under either hypothesis about `analysis`."""

    def __init__(self, honour_analysis, everything):
        self.honour_analysis = honour_analysis
        self.everything = everything
        self.requested = []
        self._last = None

    def post(self, url, headers, payload):
        chunk = payload.get("analysis")
        self.requested.append(list(chunk) if chunk else None)
        names = list(chunk) if (self.honour_analysis and chunk) else list(self.everything)
        self._last = _env_body(names)
        return {"data": {"activity_id": "abc"}}

    def get(self, url, headers):
        return self._last


ALL_PARAMS = ["wet_bulb_temperature_celsius", "relative_humidity_percent",
              "apparent_temperature_celsius", "cloud_cover_octas", "precipitation_mm"]
M1_NEEDS = ALL_PARAMS[:4]


def test_cap_binding_is_handled_by_chunking(tmp_path):
    """If `analysis` IS honoured and capped at 3, four parameters still arrive."""
    transport = ChunkAwareTransport(honour_analysis=True, everything=ALL_PARAMS)
    client = FortyGuardClient(cache=DiskCache(str(tmp_path)), transport=transport,
                              refresh=True, sleep=lambda _s: None)
    response = client.environmental_parameters(
        latitude=33.4484, longitude=-112.0740, temperature=39.5,
        start_date="2024-07-15", analysis=M1_NEEDS)
    assert response.chunks == 2
    assert [len(c) for c in transport.requested] == [3, 1]
    assert sorted(response.returned) == sorted(M1_NEEDS)
    assert response.analysis_honoured is True
    assert "cap is real" in response.note


def test_cap_not_binding_is_handled_too_and_costs_one_call(tmp_path):
    """If `analysis` is IGNORED, the first chunk already returned everything, so
    the client must stop rather than pay for a second identical call."""
    transport = ChunkAwareTransport(honour_analysis=False, everything=ALL_PARAMS)
    client = FortyGuardClient(cache=DiskCache(str(tmp_path)), transport=transport,
                              refresh=True, sleep=lambda _s: None)
    response = client.environmental_parameters(
        latitude=33.4484, longitude=-112.0740, temperature=39.5,
        start_date="2024-07-15", analysis=M1_NEEDS)
    assert response.chunks == 1, "paid for a second call it did not need"
    assert sorted(response.returned) == sorted(ALL_PARAMS)
    assert response.analysis_honoured is False
    assert "IGNORED" in response.note


def test_a_short_request_is_never_chunked(tmp_path):
    transport = ChunkAwareTransport(honour_analysis=True, everything=ALL_PARAMS)
    client = FortyGuardClient(cache=DiskCache(str(tmp_path)), transport=transport,
                              refresh=True, sleep=lambda _s: None)
    response = client.environmental_parameters(
        latitude=1.0, longitude=2.0, temperature=3.0, start_date="2024-07-15",
        analysis=M1_NEEDS[:3])
    assert response.chunks == 1
    assert len(transport.requested) == 1


def test_merged_result_parses_as_a_normal_env_params_day(tmp_path):
    """Whatever chunking did, downstream must not be able to tell."""
    transport = ChunkAwareTransport(honour_analysis=True, everything=ALL_PARAMS)
    client = FortyGuardClient(cache=DiskCache(str(tmp_path)), transport=transport,
                              refresh=True, sleep=lambda _s: None)
    response = client.environmental_parameters(
        latitude=33.4484, longitude=-112.0740, temperature=39.5,
        start_date="2024-07-15", analysis=M1_NEEDS)
    day = parse_env_params({"data": {"result": response.result}})
    assert len(day.hourly("cloud_cover_octas")) == 24
    assert day.utc_offset_hours == -7


def test_the_real_env_params_fixture_still_parses_through_the_client(seeded):
    cache, _ = seeded
    client = FortyGuardClient(cache=cache, transport=OfflineTransport())
    entry = next(e for e in seed.load_index(FixtureStore())
                 if e["method"] == "environmental_parameters")
    response = client.environmental_parameters(**entry["kwargs"])
    day = parse_env_params({"data": {"result": response.result}})
    assert day.hourly("wet_bulb_temperature_celsius")[14] == pytest.approx(23.7)
    # The committed response carried 15 parameters for a 3-parameter request.
    assert len(response.returned) == 15
    assert response.analysis_honoured is False


# ---------------------------------------------------------------------------
# The network quarantine
# ---------------------------------------------------------------------------


NETWORK_IMPORTS = re.compile(
    r"^\s*(?:import|from)\s+(requests|httpx|urllib|urllib3|http|socket|aiohttp)\b",
    re.MULTILINE,
)
ALLOWED = {os.path.join("sources", "transport.py")}


def test_networking_is_quarantined_to_exactly_one_module():
    """SPEC.md hard constraint 6, made checkable.

    M0 has to be able to make live calls, so the package can no longer be
    entirely free of networking. Instead it is confined to one file, and every
    other module — all the physics, the pipeline, the parsers, the cache — stays
    provably offline.
    """
    package = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "src", "acclimate"))
    offenders = []
    for root, _dirs, files in os.walk(package):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            relative = os.path.relpath(path, package)
            with open(path, "r", encoding="utf-8") as fh:
                if NETWORK_IMPORTS.search(fh.read()) and relative not in ALLOWED:
                    offenders.append(relative)
    assert not offenders, "networking imported outside the quarantine: %s" % offenders


def test_the_quarantined_module_is_not_imported_by_default():
    """Importing the package must not pull in a networking stack."""
    import subprocess
    import sys

    code = (
        "import sys; sys.path.insert(0, 'src');"
        "import acclimate.reference, acclimate.wbgt;"
        "print('requests' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=os.path.join(os.path.dirname(__file__), ".."))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False", out.stdout
