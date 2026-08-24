"""Turn the committed fixtures into cache entries.

M0's exit test: "with the network disconnected, every fixture request returns
from cache." That only holds if the cache knows which request produced each
committed payload — a raw response on disk carries no record of what was asked
for.

`fixtures/INDEX.json` supplies the missing half. Each entry names the client call
that produced a fixture; seeding replays those calls through the SAME payload
builders the live client uses, so a seeded key and a live key cannot drift apart.
If someone changes a payload builder, the seeded keys move with it and the
fixtures keep resolving.

Entries marked role="derived" are summaries and regression artefacts, not raw API
responses. They are listed for provenance and deliberately NOT seeded — caching
a summary under an endpoint key would let a summary masquerade as a response.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from acclimate.sources.cache import DiskCache, cache_key
from acclimate.sources.client import (
    ENV_PARAMS,
    HEATMAP,
    SATELLITE,
    build_env_params_payload,
    build_heatmap_payload,
)
from acclimate.sources.fixtures import FixtureStore

INDEX_FILE = "INDEX.json"

BUILDERS = {
    "create_heatmap": (HEATMAP, build_heatmap_payload),
    "environmental_parameters": (ENV_PARAMS, build_env_params_payload),
}
# satellite has no builder yet; declared so an entry for it fails loudly.
ENDPOINTS = {"create_heatmap": HEATMAP, "environmental_parameters": ENV_PARAMS,
             "satellite_segmentation": SATELLITE}


@dataclass
class SeedResult:
    seeded: List[Tuple[str, str]]      # (fixture file, cache key)
    already_present: List[str]
    derived_skipped: List[str]
    missing_files: List[str]

    @property
    def ok(self) -> bool:
        return not self.missing_files

    def summary(self) -> str:
        return (
            "seeded %d, already present %d, derived skipped %d, missing %d"
            % (len(self.seeded), len(self.already_present),
               len(self.derived_skipped), len(self.missing_files))
        )


def load_index(store: Optional[FixtureStore] = None) -> List[Dict[str, Any]]:
    store = store or FixtureStore()
    path = store.path(INDEX_FILE)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            "fixtures/INDEX.json is missing. It is what lets the cache resolve a "
            "request to a committed payload; without it M0's exit test cannot pass."
        )
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def payload_for(entry: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """(endpoint, request payload) for one index entry."""
    method = entry["method"]
    if method not in BUILDERS:
        raise ValueError(
            "no payload builder for method %r (entry %s)" % (method, entry.get("file"))
        )
    endpoint, builder = BUILDERS[method]
    return endpoint, builder(**entry["kwargs"])


def seed_cache(
    cache: Optional[DiskCache] = None, store: Optional[FixtureStore] = None
) -> SeedResult:
    """Write a cache entry for every raw fixture declared in the index."""
    store = store or FixtureStore()
    cache = cache or DiskCache()
    result = SeedResult([], [], [], [])

    for entry in load_index(store):
        name = entry["file"]
        if entry.get("role") == "derived":
            result.derived_skipped.append(name)
            continue
        if not store.exists(name):
            result.missing_files.append(name)
            continue
        endpoint, payload = payload_for(entry)
        response = store.load(name)
        _path, written = cache.seed(endpoint, payload, response)
        key = cache_key(endpoint, payload)
        if written:
            result.seeded.append((name, key))
        else:
            result.already_present.append(name)
    return result
