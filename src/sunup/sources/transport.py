"""The ONLY module in this package permitted to touch the network.

Everything else, every physics module, the WBGT pipeline, the parsers, the
cache, is provably offline, and `tests/test_m0_client.py` enforces that by
grepping the package for networking imports and allowing exactly this file.

Keeping the quarantine to one file is what makes "the demo runs with zero live
calls" a property you can check rather than a claim you have to trust.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sunup.errors import LiveCallBlocked


class Transport:
    """Interface. Implementations either make a call or refuse to."""

    def post(self, url: str, headers: Dict[str, str], payload: Any) -> Any:
        raise NotImplementedError

    def get(self, url: str, headers: Dict[str, str]) -> Any:
        raise NotImplementedError


class OfflineTransport(Transport):
    """Refuses every call. The default, so the network is opt-in.

    The error names the endpoint and the payload, so a cache miss during the
    demo tells you exactly which fixture is absent instead of hanging on a
    socket.
    """

    def _refuse(self, url: str, payload: Any = None) -> None:
        raise LiveCallBlocked(
            "live call blocked (offline transport): %s\n"
            "  payload: %s\n"
            "  This build defaults to offline. Pass a RequestsTransport and "
            "refresh=True to allow live calls." % (url, payload)
        )

    def post(self, url: str, headers: Dict[str, str], payload: Any) -> Any:
        self._refuse(url, payload)

    def get(self, url: str, headers: Dict[str, str]) -> Any:
        self._refuse(url)


class RequestsTransport(Transport):
    """Real HTTP. `requests` is imported lazily so importing this module, which
    `sources/__init__` does not do, never pulls in a networking stack."""

    def __init__(self, timeout_s: float = 60.0) -> None:
        self.timeout_s = timeout_s
        self.calls = 0

    def _session(self):
        import requests  # noqa: F401  (quarantined: see module docstring)

        return requests

    def post(self, url: str, headers: Dict[str, str], payload: Any) -> Any:
        requests = self._session()
        self.calls += 1
        response = requests.post(url, headers=headers, json=payload, timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()

    def get(self, url: str, headers: Dict[str, str]) -> Any:
        requests = self._session()
        self.calls += 1
        response = requests.get(url, headers=headers, timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()


class RecordingTransport(Transport):
    """Wraps another transport and remembers every call. For tests and audits."""

    def __init__(self, inner: Optional[Transport] = None) -> None:
        self.inner = inner or OfflineTransport()
        self.posts = []
        self.gets = []

    def post(self, url: str, headers: Dict[str, str], payload: Any) -> Any:
        self.posts.append((url, payload))
        return self.inner.post(url, headers, payload)

    def get(self, url: str, headers: Dict[str, str]) -> Any:
        self.gets.append(url)
        return self.inner.get(url, headers)

    @property
    def call_count(self) -> int:
        return len(self.posts) + len(self.gets)
