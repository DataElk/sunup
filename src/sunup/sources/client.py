"""M0, typed client over the endpoints in FORTYGUARD_API_CONTRACT.md.

Every method goes through the disk cache first. `refresh` defaults to False and
the transport defaults to OfflineTransport, so the network is opt-in twice over:
you have to ask for a live transport AND set refresh before a socket opens.

Contract behaviours implemented here rather than left to callers:
  - async submit/poll (section 1), status matched case-insensitively, `Failed`
    terminal, 3 s interval
  - the two response envelopes (section 1) unwrapped defensively
  - `analysis` CAP TOLERANCE on /v1/env_params (section 6), see below
  - clamping of exceedance/persistence values happens at ingest, in
    `fortyguard.parse_analysis_grid`, not here; this client returns raw payloads
    so the cache holds exactly what the API said

CAP TOLERANCE, and why it is built this way. Section 2 says Basic/Startup tiers
cap `analysis` at three parameters. Two live probes on 2026-08-24 tried to settle
whether `analysis` is honoured at all and never completed. The question is open
(section 6). So this client does not depend on the answer: it splits any
`analysis` list into chunks of ENV_PARAMS_MAX_ANALYSIS and merges the responses.

  - If the cap binds, each chunk is legal and the merge reassembles the whole set.
  - If `analysis` is ignored, every chunk returns everything and the merge is a
    no-op union, same answer, and only one chunk is ever needed.
  - If the list is short enough to fit in one chunk, there is exactly one call
    and chunking costs nothing at all.

The client also OBSERVES the answer as a side effect: if a response carries more
parameters than the chunk requested, `analysis` is not being honoured. That is
recorded on the result so the next real backfill settles the open question
without a dedicated probe.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from sunup import constants as C
from sunup.errors import ActivityFailed, CacheMiss, PollTimeout
from sunup.sources.cache import DiskCache
from sunup.sources.fixtures import unwrap_result
from sunup.sources.transport import OfflineTransport, Transport

HEATMAP = "/v1/heatmap"
ENV_PARAMS = "/v1/env_params"
SATELLITE = "/v1/satellite"
STATUS = "/v1/status"
USAGE = "/v1/system/fetch-api-key-custom-usage"

COMPLETED = ("completed", "succeeded")
FAILED = "failed"


@dataclass
class CallRecord:
    """What the client did, so a run can be audited after the fact."""

    endpoint: str
    served_from: str  # "cache" | "live"
    key: str
    activity_id: Optional[str] = None
    polls: int = 0
    transient_errors: int = 0


@dataclass
class EnvParamsResponse:
    """Merged result of one or more chunked env_params calls."""

    result: Dict[str, Any]
    chunks: int
    requested: Optional[Sequence[str]]
    returned: Sequence[str]
    analysis_honoured: Optional[bool]
    records: List[CallRecord] = field(default_factory=list)

    @property
    def note(self) -> str:
        if self.analysis_honoured is None:
            return "analysis not specified; endpoint returned everything"
        if self.analysis_honoured:
            return (
                "analysis IS honoured (response matched the request), so the "
                "3-parameter cap is real; chunking was necessary"
            )
        return (
            "analysis is IGNORED (response carried %d parameters for a %d-parameter "
            "request), so the cap does not bind on this key"
            % (len(self.returned), len(self.requested or ()))
        )


class FortyGuardClient:
    """Cache-first client. Offline and non-refreshing by default."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = C.FORTYGUARD_BASE_URL,
        cache: Optional[DiskCache] = None,
        transport: Optional[Transport] = None,
        refresh: bool = False,
        poll_interval_s: float = C.POLL_INTERVAL_S,
        poll_timeout_s: float = C.POLL_TIMEOUT_S,
        sleep=time.sleep,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.cache = cache or DiskCache(refresh=refresh)
        self.transport = transport or OfflineTransport()
        self.refresh = refresh
        self.poll_interval_s = poll_interval_s
        self.poll_timeout_s = poll_timeout_s
        self._sleep = sleep
        self.records: List[CallRecord] = []

    #, plumbing ------------------------------------------------------------

    @property
    def _headers(self) -> Dict[str, str]:
        return {"api-key": self.api_key or "", "Content-Type": "application/json"}

    def _cached_or_live(self, endpoint: str, payload: Dict[str, Any]) -> Any:
        """The single choke point. Nothing reaches the transport around this."""
        from sunup.sources.cache import cache_key

        key = cache_key(endpoint, payload)
        if not self.refresh:
            try:
                response = self.cache.get(endpoint, payload)
                self.records.append(CallRecord(endpoint, "cache", key))
                return response
            except CacheMiss:
                pass

        response = self._submit_and_wait(endpoint, payload, key)
        self.cache.put(endpoint, payload, response)
        return response

    def _submit_and_wait(self, endpoint: str, payload: Dict[str, Any], key: str) -> Any:
        submitted = self.transport.post(self.base_url + endpoint, self._headers, payload)
        activity_id = (
            (submitted.get("data") or {}).get("activity_id")
            or submitted.get("activity_id")
        )
        if not activity_id:
            # Some endpoints answer synchronously; nothing to poll.
            self.records.append(CallRecord(endpoint, "live", key))
            return submitted

        record = CallRecord(endpoint, "live", key, activity_id=activity_id)
        self.records.append(record)
        deadline = time.time() + self.poll_timeout_s
        consecutive_errors = 0
        while True:
            self._sleep(self.poll_interval_s)
            record.polls += 1
            # [MEASURED 2026-08-24] A 46 931-cell exceedance grid is a 15 MB
            # response, and the gateway intermittently 504s while serialising
            # it. The activity is fine, the very next poll returned 200 and a
            # completed result. Propagating that error would throw away an
            # activity that has already been paid for, so transient failures are
            # absorbed and only a sustained run of them gives up.
            try:
                body = self.transport.get(
                    "%s%s/%s" % (self.base_url, STATUS, activity_id), self._headers
                )
                consecutive_errors = 0
            except Exception as error:  # noqa: BLE001 - transport-agnostic by design
                consecutive_errors += 1
                record.transient_errors += 1
                if consecutive_errors > C.POLL_MAX_CONSECUTIVE_ERRORS:
                    raise PollTimeout(
                        "activity %s: %d consecutive polling failures on %s, last "
                        "was %s: %s. The activity may still be running, retrieve "
                        "it by id rather than resubmitting."
                        % (activity_id, consecutive_errors, endpoint,
                           type(error).__name__, str(error)[:200])
                    )
                if time.time() > deadline:
                    raise PollTimeout(
                        "activity %s timed out on %s while polling was erroring"
                        % (activity_id, endpoint))
                continue
            status = str((body.get("data") or {}).get("status", "")).lower()
            if status in COMPLETED:
                return body
            if status == FAILED:
                raise ActivityFailed(
                    "activity %s failed on %s (failed tasks are free)"
                    % (activity_id, endpoint)
                )
            if time.time() > deadline:
                raise PollTimeout(
                    "activity %s still %r after %.0f s on %s. The id is kept so it "
                    "can be retrieved later without paying twice."
                    % (activity_id, status or "unknown", self.poll_timeout_s, endpoint)
                )

    #, endpoints -----------------------------------------------------------

    def create_heatmap(self, **kwargs) -> Any:
        """POST /v1/heatmap. See contract sections 4 and 5."""
        return self._cached_or_live(HEATMAP, build_heatmap_payload(**kwargs))

    def environmental_parameters(self, **kwargs) -> "EnvParamsResponse":
        return self._environmental_parameters(**kwargs)

    def _environmental_parameters(
        self,
        latitude: float,
        longitude: float,
        temperature: float,
        start_date: str,
        filter_type: int = 3,
        analysis: Optional[Sequence[str]] = None,
        max_per_request: int = C.ENV_PARAMS_MAX_ANALYSIS,
    ) -> EnvParamsResponse:
        """POST /v1/env_params, chunked so the 3-parameter cap cannot bite.

        `temperature` is an INPUT ANCHOR you supply, not an output (contract
        section 6). It is echoed back on the response.
        """
        def body(chunk):
            return build_env_params_payload(
                latitude, longitude, temperature, start_date, filter_type, chunk
            )

        if not analysis:
            raw = self._cached_or_live(ENV_PARAMS, body(None))
            result = unwrap_result(raw)
            returned = sorted((result["locations"][0].get("parameters") or {}))
            return EnvParamsResponse(
                result=result,
                chunks=1,
                requested=None,
                returned=returned,
                analysis_honoured=None,
                records=list(self.records[-1:]),
            )

        wanted = list(analysis)
        chunks = [
            wanted[i : i + max_per_request] for i in range(0, len(wanted), max_per_request)
        ]
        merged: Optional[Dict[str, Any]] = None
        parameters: Dict[str, Any] = {}
        honoured: Optional[bool] = None
        records: List[CallRecord] = []

        for chunk in chunks:
            raw = self._cached_or_live(ENV_PARAMS, body(chunk))
            records.append(self.records[-1])
            result = unwrap_result(raw)
            location = result["locations"][0]
            got = location.get("parameters") or {}
            # The passive observation the stalled probe never delivered.
            extra = set(got) - set(chunk)
            honoured = (not extra) if honoured is None else (honoured and not extra)
            parameters.update(got)
            if merged is None:
                merged = result
            if len(chunks) > 1 and not extra:
                continue
            if extra:
                # analysis is ignored: one call already returned everything.
                break

        assert merged is not None
        merged["locations"][0]["parameters"] = parameters
        return EnvParamsResponse(
            result=merged,
            chunks=len(records),
            requested=wanted,
            returned=sorted(parameters),
            analysis_honoured=honoured,
            records=records,
        )

    def satellite_segmentation(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        start_time: str = "14:00",
        filter_type: int = 1,
        granularity: int = 100,
    ) -> Any:
        """POST /v1/satellite. The most expensive endpoint measured, 14 400
        credits for a single call (contract section 8). Cache hard."""
        payload = {
            "sat": {"latitude": latitude, "longitude": longitude},
            "date_time": {
                "start_date": start_date,
                "start_time": start_time,
                "filter_type": filter_type,
            },
            "granularity": granularity,
        }
        return self._cached_or_live(SATELLITE, payload)

    def fetch_api_key_custom_usage(self) -> Any:
        return self._cached_or_live(USAGE, {})

    #, audit ---------------------------------------------------------------

    @property
    def live_calls(self) -> int:
        return sum(1 for r in self.records if r.served_from == "live")

    @property
    def cache_hits(self) -> int:
        return sum(1 for r in self.records if r.served_from == "cache")


def build_heatmap_payload(
    polygon_aoi: Dict[str, Any],
    start_date: str,
    filter_type: int,
    granularity: int = 100,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    end_date: Optional[str] = None,
    analytic_type: str = "tcm",
    threshold: Optional[float] = None,
    direction: Optional[str] = None,
) -> Dict[str, Any]:
    """Build and validate a /v1/heatmap request body.

    A module function, not a method, because the cache seeder needs to derive
    the exact same payload from `fixtures/INDEX.json` without a client. One
    builder means the seeded key and the live key cannot drift apart.

    Validates the combinations the contract calls out: the API's own error for a
    bad combination is not always informative, and a silently wrong filter_type
    produces a plausible-looking FLAT DAY rather than a failure.
    """
    if filter_type not in (1, 2, 3, 4):
        raise ValueError("filter_type must be 1, 2, 3 or 4; got %r" % filter_type)
    if granularity not in C.ALLOWED_GRANULARITIES_M:
        raise ValueError(
            "granularity must be one of %s metres; got %r"
            % (sorted(C.ALLOWED_GRANULARITIES_M), granularity)
        )
    if filter_type == 1 and not start_time:
        raise ValueError("filter_type=1 (single hour) requires start_time")
    if filter_type == 2 and not (start_time and end_time):
        raise ValueError("filter_type=2 requires start_time and end_time")
    if filter_type == 4 and not end_date:
        raise ValueError("filter_type=4 (range of days) requires end_date")
    if analytic_type in C.ANALYTIC_TYPES_NEEDING_THRESHOLD:
        if threshold is None or direction is None:
            raise ValueError(
                "analytic_type=%r requires threshold and direction" % analytic_type
            )
        if filter_type not in (2, 4):
            raise ValueError(
                "analytic_type=%r needs a multi-hour or multi-day window "
                "(filter_type 2 or 4); got %d" % (analytic_type, filter_type)
            )

    date_time: Dict[str, Any] = {"start_date": start_date, "filter_type": filter_type}
    if start_time:
        date_time["start_time"] = start_time
    if end_time:
        date_time["end_time"] = end_time
    if end_date:
        date_time["end_date"] = end_date

    payload: Dict[str, Any] = {
        "polygon_aoi": polygon_aoi,
        "date_time": date_time,
        "granularity": granularity,
        "analytic_type": analytic_type,
    }
    if threshold is not None:
        payload["threshold"] = threshold
    if direction is not None:
        payload["direction"] = direction
    return payload


def build_env_params_payload(
    latitude: float,
    longitude: float,
    temperature: float,
    start_date: str,
    filter_type: int = 3,
    analysis: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Build a /v1/env_params request body for ONE chunk.

    `temperature` is an INPUT ANCHOR you supply, not an output (contract
    section 6). List order in `analysis` is preserved, because the cache key
    hashes the payload verbatim.
    """
    payload: Dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "temperature": temperature,
        "date_time": {"start_date": start_date, "filter_type": filter_type},
    }
    if analysis:
        payload["analysis"] = list(analysis)
    return payload
