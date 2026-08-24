"""Fetch one Open-Meteo archive day and commit it as a fixture.

    python scripts/fetch_openmeteo.py --refresh

Open-Meteo's archive API is free and needs no key, but this is still a LIVE CALL
and is gated behind --refresh so it cannot fire by accident (SPEC.md hard
constraint 6; FORTYGUARD_API_CONTRACT.md section 10). Without the flag it reports
what it would do and exits.

Fills the two gaps M1 could not close from FortyGuard fixtures alone:
  - wind, which no FortyGuard endpoint returns at all (constants.py section 5d)
  - an INDEPENDENT hourly temperature series, so the amplitude comparison that
    CLAUDE.md requires has a second provider to compare against

UNITS TRAP: Open-Meteo defaults wind to km/h. We request m/s explicitly and then
assert the unit the response actually reports, rather than trusting either.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from acclimate.sources.fixtures import FixtureStore  # noqa: E402
from acclimate.sources.openmeteo import ARCHIVE_HOURLY_FIELDS, fixture_key  # noqa: E402

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

EXPECTED_UNITS = {
    "temperature_2m": "°C",
    "relative_humidity_2m": "%",
    "wet_bulb_temperature_2m": "°C",
    "shortwave_radiation": "W/m²",
    "wind_speed_10m": "m/s",
    "cloud_cover": "%",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--latitude", type=float, default=33.4484)
    parser.add_argument("--longitude", type=float, default=-112.0740)
    parser.add_argument("--date", default="2024-07-15")
    parser.add_argument("--refresh", action="store_true", help="actually make the call")
    parser.add_argument("--force", action="store_true", help="overwrite an existing fixture")
    args = parser.parse_args()

    date = dt.date.fromisoformat(args.date)
    store = FixtureStore()
    key = fixture_key(args.latitude, args.longitude, date)
    target = store.path(key)

    params = {
        "latitude": args.latitude,
        "longitude": args.longitude,
        "start_date": args.date,
        "end_date": args.date,
        "hourly": ",".join(ARCHIVE_HOURLY_FIELDS),
        "timezone": "auto",
        "wind_speed_unit": "ms",
    }

    if not args.refresh:
        print("DRY RUN. Would GET %s" % ARCHIVE_URL)
        for k, v in params.items():
            print("    %-16s %s" % (k, v))
        print("  -> %s" % target)
        print("\nRe-run with --refresh to make the call.")
        return 0

    if os.path.exists(target) and not args.force:
        print("Fixture already exists: %s" % target)
        print("Pass --force if you really mean to re-fetch.")
        return 0

    print("GET %s" % ARCHIVE_URL)
    response = requests.get(ARCHIVE_URL, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()

    hourly = payload.get("hourly") or {}
    units = payload.get("hourly_units") or {}
    missing = [f for f in ARCHIVE_HOURLY_FIELDS if f not in hourly]
    if missing:
        print("FAIL: response is missing %s" % missing)
        return 1

    print("\ntimezone   %s (%s, UTC%+d)"
          % (payload.get("timezone"), payload.get("timezone_abbreviation"),
             payload.get("utc_offset_seconds", 0) // 3600))
    print("elevation  %s m" % payload.get("elevation"))
    print("\nunits reported by the API:")
    unit_problem = False
    for field in ARCHIVE_HOURLY_FIELDS:
        got = units.get(field)
        expected = EXPECTED_UNITS[field]
        ok = got == expected
        unit_problem = unit_problem or not ok
        print("  %-22s %-8s %s" % (field, got, "ok" if ok else "EXPECTED %s" % expected))
    if unit_problem:
        print("\nFAIL: unit mismatch. Not writing the fixture — fix the request first.")
        return 1

    counts = {f: len(hourly[f]) for f in ARCHIVE_HOURLY_FIELDS}
    if set(counts.values()) != {24}:
        print("\nFAIL: expected 24 hourly values per field, got %s" % counts)
        return 1

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print("\nwrote %s (%d bytes)" % (target, os.path.getsize(target)))

    temps = hourly["temperature_2m"]
    winds = hourly["wind_speed_10m"]
    print("\n  temperature_2m     %.2f .. %.2f degC (amplitude %.2f)"
          % (min(temps), max(temps), max(temps) - min(temps)))
    print("  wind_speed_10m     %.2f .. %.2f m/s (mean %.2f)"
          % (min(winds), max(winds), sum(winds) / len(winds)))
    print("  shortwave peak     %.1f W/m2" % max(hourly["shortwave_radiation"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
