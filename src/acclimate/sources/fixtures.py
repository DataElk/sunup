"""Locating and loading raw payloads from ``fixtures/``.

FORTYGUARD_API_CONTRACT.md section 1: the response envelope differs by access
path. ``client.create_heatmap`` returns ``{"activity_id", "result"}`` while a raw
``GET /v1/status/{id}`` returns ``{"error", "status_code", "message", "data":
{"activity_id", "status", "result"}}``. The fixtures contain both shapes — one
per file, depending on which script captured it — so unwrapping is defensive.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from acclimate.errors import FixtureNotFound

_THIS = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FIXTURE_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", "..", "fixtures"))


class FixtureStore:
    """Loads raw payloads by relative path under the fixtures root."""

    def __init__(self, root: Optional[str] = None) -> None:
        self.root = os.path.abspath(root or DEFAULT_FIXTURE_ROOT)

    def path(self, relative: str) -> str:
        return os.path.join(self.root, relative.replace("/", os.sep))

    def exists(self, relative: str) -> bool:
        return os.path.isfile(self.path(relative))

    def load(self, relative: str) -> Any:
        full = self.path(relative)
        if not os.path.isfile(full):
            raise FixtureNotFound(
                "no cached payload at %s (fixtures root %s). This build makes no "
                "live calls; capture it and commit it per fixtures/MANIFEST.md."
                % (relative, self.root)
            )
        with open(full, "r", encoding="utf-8") as fh:
            return json.load(fh)


def unwrap_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return the ``result`` body regardless of which envelope wrapped it.

    Some fixtures were saved already unwrapped (``filter3_properties_*.json`` is
    the bare result), so a payload that already looks like a result is returned
    untouched.
    """
    if not isinstance(payload, dict):
        raise TypeError("expected a JSON object, got %s" % type(payload).__name__)

    result = payload.get("result")
    if isinstance(result, dict):
        return result

    data = payload.get("data")
    if isinstance(data, dict):
        inner = data.get("result")
        if isinstance(inner, dict):
            return inner

    # Already a bare result body.
    if "map_data" in payload or "locations" in payload or "metadata" in payload:
        return payload

    raise KeyError(
        "could not find a result body; top-level keys were %s"
        % sorted(payload.keys())[:12]
    )
