"""Disk cache keyed on a hash of the full request.

SPEC.md hard constraint 6 and FORTYGUARD_API_CONTRACT.md section 10: the demo
must run with zero live calls, and live calls sit behind a REFRESH flag that
defaults to False.

The key is a SHA-256 over the endpoint plus the canonicalised request payload,
so two calls collide only if they would have produced the same response. Nothing
about the key depends on when the call was made or what the response looked like.

Committed fixtures are the cache SEED. `fixtures/INDEX.json` declares, for each
committed payload, the client call that produced it; `seed_from_index` turns
those declarations into cache entries so a cold checkout serves every fixture
request from disk without a network.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from acclimate.errors import CacheMiss

_THIS = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CACHE_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", "..", "data", "cache"))


def canonical(payload: Any) -> str:
    """Stable JSON: sorted keys, no incidental whitespace.

    Two payloads that differ only in key order or float formatting must produce
    the same key, or the cache silently misses and the demo hits the network.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def cache_key(endpoint: str, payload: Any) -> str:
    digest = hashlib.sha256(
        canonical({"endpoint": endpoint, "payload": payload}).encode("utf-8")
    ).hexdigest()
    return "%s_%s" % (endpoint.strip("/").replace("/", "-"), digest[:32])


@dataclass(frozen=True)
class CacheEntry:
    key: str
    path: str
    source: str  # "cache" | "fixture-seed"


class DiskCache:
    """Read-through cache over a directory of raw JSON responses."""

    def __init__(self, root: Optional[str] = None, refresh: bool = False) -> None:
        self.root = os.path.abspath(root or DEFAULT_CACHE_ROOT)
        self.refresh = refresh
        self._index: Dict[str, str] = {}

    #, paths ---------------------------------------------------------------

    def path_for(self, endpoint: str, payload: Any) -> str:
        return os.path.join(self.root, cache_key(endpoint, payload) + ".json")

    def has(self, endpoint: str, payload: Any) -> bool:
        return os.path.isfile(self.path_for(endpoint, payload))

    #, read / write --------------------------------------------------------

    def get(self, endpoint: str, payload: Any) -> Any:
        path = self.path_for(endpoint, payload)
        if not os.path.isfile(path):
            raise CacheMiss(
                "no cache entry for %s key=%s\n  payload: %s"
                % (endpoint, cache_key(endpoint, payload), canonical(payload)[:400])
            )
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def put(self, endpoint: str, payload: Any, response: Any) -> str:
        path = self.path_for(endpoint, payload)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(response, fh)
        os.replace(tmp, path)  # atomic: a killed process cannot leave half a file
        return path

    #, seeding -------------------------------------------------------------

    def seed(self, endpoint: str, payload: Any, response: Any) -> Tuple[str, bool]:
        """Write only if absent. Returns (path, written)."""
        if self.has(endpoint, payload):
            return self.path_for(endpoint, payload), False
        return self.put(endpoint, payload, response), True

    def stats(self) -> Dict[str, int]:
        if not os.path.isdir(self.root):
            return {"entries": 0, "bytes": 0}
        entries = [f for f in os.listdir(self.root) if f.endswith(".json")]
        return {
            "entries": len(entries),
            "bytes": sum(os.path.getsize(os.path.join(self.root, f)) for f in entries),
        }
