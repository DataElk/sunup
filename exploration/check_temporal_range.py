"""
check_temporal_range.py

THE ONE REMAINING UNKNOWN.

For 2024-07-15, filter_type=3 returned a per-cell temporal min/max spanning
10.87 C — the real diurnal swing. If 2026 dates do the same, the hourly
reconstruction strategy works: one call per site per day gives amplitude and
offset, and Open-Meteo supplies the diurnal shape.

If 2026 dates collapse min == avg == max, that strategy is dead and the data
layer needs redesigning before anything else is built.

This script answers it. ~4 heatmap calls, a few thousand credits.

    python check_temporal_range.py
"""

import json
from dotenv import load_dotenv
from fortyguard import FortyGuardClient

load_dotenv()
client = FortyGuardClient()

# Same downtown Phoenix polygon used in every previous pull, so results are
# directly comparable to the 2024 baseline.
PHOENIX_PARCEL = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-112.0790, 33.4450],
                [-112.0690, 33.4450],
                [-112.0690, 33.4550],
                [-112.0790, 33.4550],
                [-112.0790, 33.4450],
            ]],
        },
    }],
}

# 2024-07-15 is the known-good control. If it does not show a diurnal range,
# something changed in the API and the whole contract needs rechecking.
DATES = ["2024-07-15", "2026-08-09", "2026-08-05", "2026-07-26"]

CONTROL_DATE = "2024-07-15"
CONTROL_EXPECTED_RANGE_C = 10.87   # verified 2026-08-23


def unwrap(resp):
    return resp.get("result") or resp.get("data", {}).get("result", {}) or {}


results = {}

for date in DATES:
    print(f"\n{'='*72}\n{date}  —  filter_type=3 (full day)\n{'='*72}")

    resp = client.create_heatmap(
        polygon_aoi=PHOENIX_PARCEL,
        start_date=date,
        filter_type=3,
        granularity=100,
    )

    result = unwrap(resp)
    features = result.get("map_data", {}).get("features", [])
    stats = result.get("stats_data", {}).get("temperature_stats", {})

    if not features:
        print("  NO FEATURES RETURNED — record this, it is itself a finding.")
        results[date] = {"error": "no features", "raw_stats": stats}
        continue

    # --- THE ACTUAL QUESTION -------------------------------------------------
    # stats_data.temperature_stats is SPATIAL (across cells).
    # features[i].properties.{min,max}_temperature is TEMPORAL (within the day).
    # These are different axes and are easy to confuse. We want the temporal one.
    print("\n  RAW properties of features[0]:")
    print("  " + json.dumps(features[0]["properties"], indent=2).replace("\n", "\n  "))

    ranges = []
    for f in features:
        p = f["properties"]
        lo, hi = p.get("min_temperature"), p.get("max_temperature")
        if lo is not None and hi is not None:
            ranges.append(hi - lo)

    if not ranges:
        print("\n  min_temperature / max_temperature ABSENT from properties.")
        results[date] = {"verdict": "FIELDS_ABSENT"}
        continue

    max_range = max(ranges)
    mean_range = sum(ranges) / len(ranges)

    # Spatial spread, for contrast — this is the axis that is legitimately flat
    # at parcel scale and must not be mistaken for the diurnal range.
    spatial = stats.get("maximum", 0) - stats.get("minimum", 0)

    print(f"\n  cells                      : {len(features)}")
    print(f"  TEMPORAL range (per cell)  : mean {mean_range:.3f} C, max {max_range:.3f} C")
    print(f"  SPATIAL spread (all cells) : {spatial:.3f} C")

    # A real Phoenix summer day swings ~10 C. Anything under 2 C is a collapse.
    if max_range < 0.5:
        verdict = "COLLAPSED"
        print("\n  >>> COLLAPSED. min == avg == max. No diurnal information.")
    elif max_range < 2.0:
        verdict = "DEGRADED"
        print(f"\n  >>> DEGRADED. {max_range:.2f} C is far below a real diurnal swing.")
    else:
        verdict = "USABLE"
        print(f"\n  >>> USABLE. {max_range:.2f} C diurnal range present.")

    results[date] = {
        "verdict": verdict,
        "temporal_range_mean_c": round(mean_range, 4),
        "temporal_range_max_c": round(max_range, 4),
        "spatial_spread_c": round(spatial, 4),
        "n_cells": len(features),
        "sample_properties": features[0]["properties"],
    }

    with open(f"filter3_properties_{date}.json", "w") as fh:
        json.dump(result, fh, indent=2)


# ---------------------------------------------------------------------------
# VERDICT
# ---------------------------------------------------------------------------
print(f"\n\n{'='*72}\nVERDICT\n{'='*72}\n")
print(f"{'date':<14}{'verdict':<14}{'temporal':>10}{'spatial':>10}")
for d in DATES:
    r = results.get(d, {})
    print(f"{d:<14}{r.get('verdict','ERROR'):<14}"
          f"{r.get('temporal_range_max_c','-'):>10}"
          f"{r.get('spatial_spread_c','-'):>10}")

control = results.get(CONTROL_DATE, {})
recent = [results.get(d, {}) for d in DATES if d.startswith("2026")]

print()
if control.get("verdict") != "USABLE":
    print("CONTROL FAILED. 2024-07-15 no longer shows the verified 10.87 C range.")
    print("The API changed. Re-verify FORTYGUARD_API_CONTRACT.md before building.")
elif all(r.get("verdict") == "USABLE" for r in recent):
    print("PASS — 2026 dates carry diurnal range.")
    print("The reconstruction strategy in CLAUDE.md stands. Build M0 as written.")
else:
    print("FAIL — 2026 dates do not carry usable diurnal range.")
    print("The one-call-per-site-day strategy is dead. Options, in order:")
    print("  1. Open-Meteo hourly for the SHAPE and the AMPLITUDE; FortyGuard")
    print("     filter_type=3 daily mean only for the site-specific OFFSET.")
    print("     Cheapest. Weakens the spatial claim but does not break it.")
    print("  2. filter_type=2 (range of hours) — test whether it returns")
    print("     per-hour data or one aggregate. Untested. Try this before 3.")
    print("  3. 24x filter_type=1 calls per site-day. Correct but ~336 calls per")
    print("     site for a 14-day backfill. Only viable for 2-3 demo sites.")
    print("\nUpdate CLAUDE.md and FORTYGUARD_API_CONTRACT.md before writing code.")

with open("temporal_range_verdict.json", "w") as fh:
    json.dump(results, fh, indent=2)
print("\nSaved verdict to temporal_range_verdict.json")
