"""Is /v1/env_params FortyGuard's own data, or a re-serve of Open-Meteo?

    python scripts/audit_env_params_provenance.py --refresh   # fetch, then audit
    python scripts/audit_env_params_provenance.py             # audit from fixtures

WHY THIS MATTERS MORE THAN IT LOOKS. On 2026-08-24 we found FortyGuard's
`cloud_cover_octas` byte-identical to Open-Meteo's `cloud_cover` across all 24
hours. If that holds for more parameters, then treating the two as independent
sources is wrong, and any writeup sentence of the form "FortyGuard agrees with
Open-Meteo, so the value is corroborated" is circular.

The distinction the writeup needs:
  - SHARED   -> re-serve of a public reanalysis. Free elsewhere. Not evidence.
  - DERIVED  -> genuinely FortyGuard. This is what the product is actually buying.

We compare every hourly parameter `/v1/env_params` returns against the closest
Open-Meteo field, at three strengths:
  IDENTICAL   every one of 24 values matches exactly
  ROUNDED     matches after rounding to the coarser of the two precisions
  CORRELATED  not equal, but tracks closely (max |diff| small)
  DIFFERENT   genuinely different numbers

Live calls are gated behind --refresh. Both Open-Meteo endpoints are free and
need no key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from acclimate.sources.fixtures import FixtureStore  # noqa: E402
from acclimate.sources.fortyguard import parse_env_params  # noqa: E402

LAT, LON, DATE = 33.4484, -112.0740, "2024-07-15"

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
AIRQUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

WEATHER_FIXTURE = "provenance/openmeteo_weather_%s.json" % DATE
AIRQUALITY_FIXTURE = "provenance/openmeteo_airquality_%s.json" % DATE

WEATHER_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "apparent_temperature",
    "wet_bulb_temperature_2m",
    "precipitation",
    "cloud_cover",
    "surface_pressure",
    "wind_speed_10m",
    "shortwave_radiation",
    "direct_normal_irradiance",
    "diffuse_radiation",
]

AIRQUALITY_FIELDS = [
    "pm10",
    "pm2_5",
    "carbon_monoxide",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
    "methane",
    "us_aqi",
    "us_aqi_pm2_5",
    "us_aqi_pm10",
    "us_aqi_nitrogen_dioxide",
    "us_aqi_carbon_monoxide",
    "us_aqi_ozone",
    "us_aqi_sulphur_dioxide",
    "european_aqi",
]

# FortyGuard parameter -> the Open-Meteo fields worth testing it against.
# Several FortyGuard air-quality fields are ambiguous (an "idx" could be a raw
# concentration or a sub-index), so each is tested against both candidates.
CANDIDATES = {
    "apparent_temperature_celsius": ["apparent_temperature", "temperature_2m"],
    "relative_humidity_percent": ["relative_humidity_2m"],
    "wet_bulb_temperature_celsius": ["wet_bulb_temperature_2m", "dew_point_2m"],
    "precipitation_mm": ["precipitation"],
    "cloud_cover_octas": ["cloud_cover"],
    "heat_index_celsius": ["apparent_temperature"],
    "air_quality:idx": ["us_aqi", "european_aqi", "us_aqi_pm2_5", "pm2_5"],
    "air_quality_pm2p5:idx": ["us_aqi_pm2_5", "pm2_5"],
    "air_quality_pm10:idx": ["us_aqi_pm10", "pm10"],
    "air_quality_no2:idx": ["us_aqi_nitrogen_dioxide", "nitrogen_dioxide"],
    "air_quality_o3:idx": ["us_aqi_ozone", "ozone"],
    "air_quality_so2:idx": ["us_aqi_sulphur_dioxide", "sulphur_dioxide"],
    "aqi_us_co": ["us_aqi_carbon_monoxide", "carbon_monoxide"],
    "methane_ppb": ["methane"],
    "co2_ppm": [],
}


def fetch(url, params, label):
    """Request fields one batch at a time, dropping any the API rejects."""
    import requests

    wanted = list(params["hourly"])
    got = {}
    units = {}
    meta = {}
    remaining = wanted
    while remaining:
        query = dict(params, hourly=",".join(remaining))
        response = requests.get(url, params=query, timeout=90)
        if response.status_code == 400:
            # Open-Meteo names the offending variable in its error text.
            message = response.text
            dropped = [f for f in remaining if f in message]
            if not dropped:
                print("  %s: 400 with no identifiable field: %s" % (label, message[:200]))
                break
            print("  %s: dropping unsupported %s" % (label, dropped))
            remaining = [f for f in remaining if f not in dropped]
            continue
        response.raise_for_status()
        payload = response.json()
        meta = {k: v for k, v in payload.items() if k not in ("hourly", "hourly_units")}
        got = payload.get("hourly", {})
        units = payload.get("hourly_units", {})
        break
    return {"hourly": got, "hourly_units": units, "meta": meta}


def refresh(store):
    common = dict(latitude=LAT, longitude=LON, start_date=DATE, end_date=DATE,
                  timezone="auto")
    print("GET %s" % ARCHIVE_URL)
    weather = fetch(ARCHIVE_URL, dict(common, hourly=WEATHER_FIELDS,
                                      wind_speed_unit="ms"), "archive")
    print("GET %s" % AIRQUALITY_URL)
    air = fetch(AIRQUALITY_URL, dict(common, hourly=AIRQUALITY_FIELDS), "air-quality")

    for key, payload in ((WEATHER_FIXTURE, weather), (AIRQUALITY_FIXTURE, air)):
        path = store.path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print("  wrote %s (%d fields)" % (key, len(payload["hourly"]) - 1))


def quantum(values):
    """The smallest step every value in the series is a multiple of.

    FortyGuard reports relative humidity to 0.1; Open-Meteo's ERA5 archive
    reports it to 1. That difference is the whole reason a naive equality test
    misreads these fields as unrelated.
    """
    for q in (1.0, 0.5, 0.1, 0.01, 0.001):
        if all(abs(round(v / q) - v / q) < 1e-6 for v in values):
            return q
    return 0.001


def classify(fg, om):
    """Compare two 24-value series at the coarser of their two precisions.

    Returns (verdict, detail). The verdicts that matter:

      IDENTICAL        every value equal, bit for bit
      SAME TO ROUNDING every value within half the coarser quantum -- i.e. the
                       two are the same number reported at different precision
      CORRELATED       tracks closely but beyond rounding
      DIFFERENT        genuinely different numbers
    """
    if om is None:
        return "NO OM FIELD", ""
    pairs = [(a, b) for a, b in zip(fg, om) if a is not None and b is not None]
    if not pairs:
        return ("BOTH NULL", "") if all(v is None for v in fg) else ("NO OVERLAP", "")
    if all(a == b for a, b in pairs):
        return "IDENTICAL", "all %d values equal" % len(pairs)

    q = max(quantum([a for a, _ in pairs]), quantum([b for _, b in pairs]))
    diffs = [abs(a - b) for a, b in pairs]
    worst = max(diffs)
    exact = sum(1 for a, b in pairs if a == b)
    if worst <= q / 2 + 1e-9:
        return ("SAME TO ROUNDING",
                "%d/24 exact, worst %.3g <= half-quantum %.3g" % (exact, worst, q / 2))
    scale = max(abs(b) for _, b in pairs) or 1.0
    if worst / scale < 0.02:
        return "CORRELATED", "worst %.4g (%.2f%% of scale)" % (worst, 100 * worst / scale)
    return "DIFFERENT", "worst %.4g, mean %.4g" % (worst, sum(diffs) / len(diffs))


def audit(store):
    env = parse_env_params(store.load("env_params/phoenix_env_params_raw.json"))
    weather = store.load(WEATHER_FIXTURE)
    air = store.load(AIRQUALITY_FIXTURE)

    om = {}
    for payload in (weather, air):
        for name, values in payload["hourly"].items():
            if name != "time" and isinstance(values, list):
                om[name] = values[:24]

    print("=" * 78)
    print("env_params PROVENANCE AUDIT  -  %s, %.4f %.4f" % (DATE, LAT, LON))
    print("=" * 78)
    print("Open-Meteo fields retrieved: %d" % len(om))
    print("  weather:      %s" % ", ".join(sorted(weather["hourly"]) ))
    print("  air quality:  %s" % ", ".join(sorted(air["hourly"])))

    shared, derived, unknown = [], [], []
    print("\n%-32s %-26s %-17s %s" % ("FortyGuard parameter", "best Open-Meteo match",
                                      "verdict", "detail"))
    print("-" * 110)
    for name in sorted(env.parameters):
        fg = list(env.parameters[name])
        best = ("NO OM FIELD", "", None, "")
        rank = {"IDENTICAL": 0, "SAME TO ROUNDING": 1, "CORRELATED": 2,
                "DIFFERENT": 3, "BOTH NULL": 4, "NO OVERLAP": 5, "NO OM FIELD": 6}
        for candidate in CANDIDATES.get(name, []):
            verdict, detail = classify(fg, om.get(candidate))
            if rank[verdict] < rank[best[0]]:
                best = (verdict, candidate, om.get(candidate), detail)
        verdict, candidate, _series, detail = best
        print("%-32s %-26s %-17s %s" % (name, candidate or "-", verdict, detail))
        if verdict in ("IDENTICAL", "SAME TO ROUNDING", "CORRELATED"):
            shared.append((name, candidate, verdict))
        elif verdict == "DIFFERENT":
            derived.append((name, candidate))
        else:
            unknown.append((name, verdict))

    # Cross-check inside FortyGuard's own response.
    print("\n" + "-" * 110)
    print("INTERNAL DUPLICATES inside the FortyGuard response:")
    names = sorted(env.parameters)
    seen = 0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            va, vb = env.parameters[a], env.parameters[b]
            if all(x is not None for x in va) and va == vb:
                print("  %s == %s  (identical 24-value series)" % (a, b))
                seen += 1
    if not seen:
        print("  none")

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    print("\nSHARED with Open-Meteo (%d) - NOT independent, NOT evidence of anything:"
          % len(shared))
    for name, candidate, verdict in shared:
        print("  %-32s = openmeteo.%-26s [%s]" % (name, candidate, verdict))
    print("\nGENUINELY DIFFERENT from Open-Meteo (%d):" % len(derived))
    for name, candidate in derived:
        print("  %-32s (closest was %s)" % (name, candidate))
    if unknown:
        print("\nUNTESTABLE (%d):" % len(unknown))
        for name, verdict in unknown:
            print("  %-32s %s" % (name, verdict))

    print("""
WHAT THE WRITEUP MAY AND MAY NOT CLAIM

  MAY NOT: "FortyGuard and Open-Meteo agree, so the value is corroborated."
           For every SHARED parameter that is circular - same numbers, one
           provider re-serving another.

  MAY:     The per-cell tile data from /v1/heatmap is the part that is
           genuinely FortyGuard's, and it is what the whole product rests on.
           The 60-100 m tiles, the per-cell diurnal min/mean/max, and the
           exceedance field have no Open-Meteo equivalent at any price.

  SO:      env_params is a convenience layer over a public reanalysis. Treat it
           as the DISTRICT context it is (contract section 6, trap 3), never as a
           second opinion on the tiles.""")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true",
                        help="make the two live Open-Meteo calls first")
    args = parser.parse_args()
    store = FixtureStore()
    if args.refresh:
        refresh(store)
        print()
    if not store.exists(WEATHER_FIXTURE):
        print("No provenance fixtures yet. Re-run with --refresh.")
        return 1
    return audit(store)


if __name__ == "__main__":
    sys.exit(main())
