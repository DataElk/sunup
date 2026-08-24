"""Background runner for the env_params `analysis` probe.

Kept separate from probe_env_params_analysis.py so the activity_id is persisted
to disk the instant it is issued. The first run lost its id when the task log
rotated, and without the id a submitted (already paid for) activity cannot be
retrieved. State goes to scripts/probe_state.json.
"""

from __future__ import annotations

import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "probe_state.json")
OUT = os.path.join(HERE, "..", "fixtures", "env_params",
                   "phoenix_env_params_single_analysis_probe.json")

PAYLOAD = {
    "latitude": 33.4484,
    "longitude": -112.0740,
    "temperature": 39.5,
    "date_time": {"start_date": "2024-07-15", "filter_type": 3},
    "analysis": ["wet_bulb_temperature_celsius"],
}


def save(**kwargs):
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(kwargs, fh, indent=2)


def main():
    load_dotenv()
    key = os.getenv("FORTYGUARD_API_KEY")
    base = os.getenv("FORTYGUARD_BASE_URL", "https://api.fortyguard.com")
    headers = {"api-key": key, "Content-Type": "application/json"}

    # Reuse an already-submitted activity if one is pending — never pay twice.
    activity_id = None
    if os.path.exists(STATE):
        try:
            prior = json.load(open(STATE, encoding="utf-8"))
            if prior.get("activity_id") and prior.get("status", "").lower() not in (
                "completed", "succeeded", "failed"
            ):
                activity_id = prior["activity_id"]
        except Exception:
            pass

    if activity_id is None:
        response = requests.post(
            base + "/v1/env_params", headers=headers, json=PAYLOAD, timeout=60
        )
        response.raise_for_status()
        activity_id = response.json()["data"]["activity_id"]
        save(activity_id=activity_id, status="submitted", poll=0)

    for attempt in range(600):
        time.sleep(3)
        body = requests.get(
            "%s/v1/status/%s" % (base, activity_id), headers=headers, timeout=60
        ).json()
        status = (body.get("data") or {}).get("status", "")
        save(activity_id=activity_id, status=status, poll=attempt + 1)
        if status.lower() in ("completed", "succeeded", "failed"):
            with open(OUT, "w", encoding="utf-8") as fh:
                json.dump(body, fh, indent=2)
            save(activity_id=activity_id, status=status, poll=attempt + 1, saved=OUT)
            return 0
    save(activity_id=activity_id, status="TIMEOUT", poll=600)
    return 1


if __name__ == "__main__":
    sys.exit(main())
