"""Does /v1/env_params honour the `analysis` parameter list?

    python scripts/probe_env_params_analysis.py --refresh

THE QUESTION. fixtures/MANIFEST.md records the captured call as requesting three
parameters, and exploration/step3_phoenix_env_params.py confirms it really did.
The committed payload contains FIFTEEN. So either `analysis` is ignored, or the
manifest is wrong about what was sent.

WHY IT MATTERS. FORTYGUARD_API_CONTRACT.md section 2 says Basic/Startup tiers are
capped at three parameters per request. The M1 WBGT pipeline needs FOUR:
wet_bulb_temperature_celsius, relative_humidity_percent,
apparent_temperature_celsius and cloud_cover_octas. If `analysis` IS applied and
the cap IS three, the M3 backfill silently loses the diurnal shape and the cloud
attenuation, and every WBGT downstream is quietly wrong.

THE TEST. Ask for exactly ONE parameter. Three outcomes:
  - response carries 1 parameter   -> `analysis` is honoured; the cap is real and
                                      the M1 request list must be split or the
                                      tier confirmed as Premium
  - response carries 15 parameters -> `analysis` is ignored; the cap is not
                                      enforced on this key; M1 is safe as-is
  - anything else                  -> record it verbatim

COST. One env_params call, measured at 2 900 credits against a 2 000 000 budget
(FORTYGUARD_API_CONTRACT.md section 8). Gated behind --refresh.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

SINGLE_PARAMETER = "wet_bulb_temperature_celsius"

# The parameters M1 actually depends on, checked against whatever comes back.
M1_REQUIRED = (
    "wet_bulb_temperature_celsius",
    "relative_humidity_percent",
    "apparent_temperature_celsius",
    "cloud_cover_octas",
)

OUT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "fixtures",
    "env_params",
    "phoenix_env_params_single_analysis_probe.json",
)


def report(path):
    """Print the verdict from an already-saved probe payload.

    Kept separate from the call so the finding can be re-derived from the
    committed fixture without spending credits again.
    """
    if not os.path.exists(path):
        print("No probe payload at %s." % os.path.relpath(path))
        print("Run with --refresh (or scripts/_probe_runner.py) first.")
        return 1
    with open(path, "r", encoding="utf-8") as fh:
        body = json.load(fh)

    status = (body.get("data") or {}).get("status", "?")
    result = (body.get("data") or {}).get("result") or body.get("result") or {}
    locations = result.get("locations") or [{}]
    parameters = locations[0].get("parameters") or {}
    names = sorted(parameters)

    print("status   %s" % status)
    print("requested analysis: [%s]  (1 parameter)" % SINGLE_PARAMETER)
    print("response carries %d parameter(s):" % len(names))
    for name in names:
        values = parameters[name]
        nulls = sum(1 for v in values if v is None) if isinstance(values, list) else "-"
        print("  %-32s len=%s nulls=%s"
              % (name, len(values) if isinstance(values, list) else "-", nulls))

    print("\nVERDICT")
    if len(names) == 1 and names[0] == SINGLE_PARAMETER:
        print("  `analysis` IS honoured. The documented 3-parameter cap is therefore")
        print("  real and binding. M1 needs 4 parameters, so the M3 backfill must")
        print("  either split the request or confirm the key is Premium.")
    elif len(names) > 1:
        print("  `analysis` is IGNORED. The endpoint returned %d parameters for a"
              % len(names))
        print("  1-parameter request, so the documented 3-parameter cap does not")
        print("  bind on this key. M1's 4-parameter dependency is safe.")
    else:
        print("  Unexpected: %s" % names)

    missing = [p for p in M1_REQUIRED if p not in parameters]
    print("\n  M1 required parameters present: %s"
          % ("ALL" if not missing else "MISSING %s" % missing))
    solar = locations[0].get("solar_irradiance")
    print("  solar_irradiance returned: %s" % ("yes" if solar else "no"))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="actually make the call")
    parser.add_argument("--report", action="store_true",
                        help="read the saved payload and print the verdict")
    args = parser.parse_args()

    if args.report:
        return report(OUT)

    load_dotenv()
    api_key = os.getenv("FORTYGUARD_API_KEY")
    base_url = os.getenv("FORTYGUARD_BASE_URL", "https://api.fortyguard.com")

    payload = {
        "latitude": 33.4484,
        "longitude": -112.0740,
        "temperature": 39.5,
        "date_time": {"start_date": "2024-07-15", "filter_type": 3},
        "analysis": [SINGLE_PARAMETER],
    }

    if not args.refresh:
        print("DRY RUN. Would POST %s/v1/env_params" % base_url)
        print(json.dumps(payload, indent=2))
        print("\nCost ~2900 credits. Re-run with --refresh.")
        return 0

    if not api_key:
        print("FORTYGUARD_API_KEY is not set. Put it in .env.")
        return 1

    headers = {"api-key": api_key, "Content-Type": "application/json"}
    print("POST %s/v1/env_params  analysis=[%s]" % (base_url, SINGLE_PARAMETER))

    submit = requests.post(
        "%s/v1/env_params" % base_url, headers=headers, json=payload, timeout=60
    )
    submit.raise_for_status()
    activity_id = submit.json()["data"]["activity_id"]
    print("activity %s" % activity_id)

    for attempt in range(60):
        time.sleep(3)
        status = requests.get(
            "%s/v1/status/%s" % (base_url, activity_id), headers=headers, timeout=60
        )
        status.raise_for_status()
        body = status.json()
        state = (body.get("data") or {}).get("status", "")
        print("  poll %2d: %s" % (attempt + 1, state))
        if state.lower() in ("completed", "succeeded"):
            break
        if state.lower() == "failed":
            print("FAILED (failed tasks are free):")
            print(json.dumps(body, indent=2)[:2000])
            return 1
    else:
        print("timed out waiting for completion")
        return 1

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=2)
    print("\nwrote %s" % os.path.relpath(OUT))

    result = (body.get("data") or {}).get("result") or {}
    locations = result.get("locations") or [{}]
    parameters = locations[0].get("parameters") or {}
    names = sorted(parameters)

    print("\nRequested 1 parameter. Response carries %d:" % len(names))
    for name in names:
        values = parameters[name]
        nulls = sum(1 for v in values if v is None) if isinstance(values, list) else "-"
        print("  %-32s len=%s nulls=%s"
              % (name, len(values) if isinstance(values, list) else "-", nulls))

    print("\nVERDICT")
    if len(names) == 1 and names[0] == SINGLE_PARAMETER:
        print("  `analysis` IS honoured. The 3-parameter cap is therefore real and")
        print("  binding. M1 needs 4 parameters -- split the request or confirm the")
        print("  key is Premium before the M3 backfill.")
    elif len(names) > 1:
        print("  `analysis` is IGNORED -- the endpoint returned %d parameters for a"
              % len(names))
        print("  1-parameter request. The documented 3-parameter cap does not bind")
        print("  on this key. M1's 4-parameter dependency is safe.")
    else:
        print("  Unexpected: %s" % names)

    missing = [p for p in M1_REQUIRED if p not in parameters]
    print("\n  M1 required parameters present: %s"
          % ("ALL" if not missing else "MISSING %s" % missing))

    solar = locations[0].get("solar_irradiance")
    print("  solar_irradiance returned: %s" % ("yes" if solar else "no"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
