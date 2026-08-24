"""M3 live retrieval: the exceedance grid and the 14-day per-site backfill.

    python scripts/m3_fetch.py --probe        one cheap parcel call, to check the
                                              API is answering before a batch
    python scripts/m3_fetch.py --exceedance   the metro grid site selection needs
    python scripts/m3_fetch.py --backfill     14 days x 2 sites, filter_type=3

Every call goes through the M0 client, so everything is cached on the way in and
a re-run costs nothing. Nothing here runs without an explicit flag.

COST DISCIPLINE. The usage endpoint returns HTTP 500, so the remaining credit
balance cannot be checked from here. Contract section 8 measured heatmap
generation at ~4 220 credits average and notes cost scales with cell count, so
an 81-cell parcel call is far cheaper than a 38 569-cell metro call. Budget:
one metro call plus 28 parcel calls. --probe exists so a batch is never started
against an API that is not answering.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from acclimate import constants as C  # noqa: E402
from acclimate import siteselection as ss  # noqa: E402
from acclimate.sources.cache import DiskCache  # noqa: E402
from acclimate.sources.client import FortyGuardClient  # noqa: E402
from acclimate.sources.fixtures import FixtureStore  # noqa: E402
from acclimate.sources.fortyguard import parse_analysis_grid  # noqa: E402
from acclimate.sources.transport import RequestsTransport  # noqa: E402

# fixtures/MANIFEST.md, the metro AOI used for the 40 degC exceedance run.
METRO_AOI = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [[
            [-112.20, 33.40], [-111.95, 33.40],
            [-111.95, 33.55], [-112.20, 33.55], [-112.20, 33.40]]]},
    }],
}

# constants.py section 8: DEMO_BACKFILL_START .. DEMO_BACKFILL_END
BACKFILL_START = dt.date.fromisoformat(C.DEMO_BACKFILL_START)
BACKFILL_END = dt.date.fromisoformat(C.DEMO_BACKFILL_END)
SELECTION_FILE = "site_selection/phoenix_40c_selection.json"


def client(refresh: bool, poll_timeout_s: float = C.POLL_TIMEOUT_S) -> FortyGuardClient:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.getcwd(), ".env"))
    return FortyGuardClient(
        api_key=os.getenv("FORTYGUARD_API_KEY"),
        base_url=os.getenv("FORTYGUARD_BASE_URL", C.FORTYGUARD_BASE_URL),
        cache=DiskCache(),
        transport=RequestsTransport(timeout_s=300),
        refresh=refresh,
        poll_timeout_s=poll_timeout_s,
    )


def backfill_dates():
    days = (BACKFILL_END - BACKFILL_START).days + 1
    return [BACKFILL_START + dt.timedelta(days=i) for i in range(days)]


def probe(args):
    """One cheap 81-cell parcel call. Confirms the API answers before a batch."""
    api = client(refresh=True)
    aoi = ss.parcel_around((C.WBGT_REFERENCE_SITE["longitude"],
                            C.WBGT_REFERENCE_SITE["latitude"]))
    date = "2026-08-06"
    print("probe: filter_type=3 parcel, %s (81 cells, cheapest call available)" % date)
    response = api.create_heatmap(
        polygon_aoi=aoi, start_date=date, filter_type=3, granularity=100)
    result = response.get("data", response).get("result", {})
    features = result.get("map_data", {}).get("features", [])
    print("  OK: %d features, %d polls" % (len(features), api.records[-1].polls))
    if features:
        p = features[0]["properties"]
        print("  tile 0: min %.2f  avg %.2f  max %.2f"
              % (p["min_temperature"], p["average_temperature"], p["max_temperature"]))
    return 0


def exceedance(args):
    """The metro grid. One large call — 38 569 cells at 100 m.

    A parcel call took 40 polls (~2 min). This one is roughly 475x the cells, so
    the poll budget is raised to an hour rather than the 15-minute default.
    """
    api = client(refresh=args.refresh, poll_timeout_s=3600.0)
    aoi = ss.buffer_polygon(METRO_AOI, C.AOI_BUFFER_KM)
    west, south, east, north = ss.bbox_of(ss.ring_of(aoi))
    print("metro AOI buffered by %.1f km -> %.4f %.4f %.4f %.4f"
          % (C.AOI_BUFFER_KM, west, south, east, north))
    print("exceedance, threshold %.0f degC, %s..%s (filter_type=4)"
          % (C.EXCEEDANCE_THRESHOLD_C, BACKFILL_START, BACKFILL_END))

    response = api.create_heatmap(
        polygon_aoi=aoi,
        start_date=BACKFILL_START.isoformat(),
        end_date=BACKFILL_END.isoformat(),
        filter_type=4,
        granularity=100,
        analytic_type="exceedance",
        threshold=C.EXCEEDANCE_THRESHOLD_C,
        direction="above",
    )
    window_hours = 24.0 * ((BACKFILL_END - BACKFILL_START).days + 1)
    grid = parse_analysis_grid(response, window_hours)
    print("  %d cells, clamped %d (%.3f%%), window %.0f h"
          % (len(grid.cells), grid.clamped_total,
             100 * grid.clamped_fraction, window_hours))

    report = ss.select_sites(grid, aoi)
    store = FixtureStore()
    path = store.path(SELECTION_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "aoi_buffered": aoi,
        "window_hours": window_hours,
        "threshold_c": C.EXCEEDANCE_THRESHOLD_C,
        "start_date": BACKFILL_START.isoformat(),
        "end_date": BACKFILL_END.isoformat(),
        "total_cells": report.total_cells,
        "discarded_edge_cells": report.discarded_edge_cells,
        "surviving_cells": report.surviving_cells,
        "edge_discard_m": report.edge_discard_m,
        "raw_min": report.raw_min,
        "raw_max": report.raw_max,
        "value_at_p%g" % report.percentile_low: report.value_at_low,
        "value_at_p%g" % report.percentile_high: report.value_at_high,
        "cool_site": {
            "centroid_lon_lat": list(report.cool_site.centroid),
            "value_hours": report.cool_site.value_hours,
            "distance_to_edge_m": report.cool_site.distance_to_edge_m,
            "percentile": report.cool_site.percentile,
        },
        "hot_site": {
            "centroid_lon_lat": list(report.hot_site.centroid),
            "value_hours": report.hot_site.value_hours,
            "distance_to_edge_m": report.hot_site.distance_to_edge_m,
            "percentile": report.hot_site.percentile,
        },
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print("\n  wrote %s" % SELECTION_FILE)
    print("  raw min/max %.2f / %.2f  (ratio %.2fx)"
          % (report.raw_min, report.raw_max, report.raw_dose_ratio))
    print("  p5 / p95    %.2f / %.2f  (ratio %.2fx)  <- after mitigation"
          % (report.value_at_low, report.value_at_high, report.dose_ratio))
    print("  cool site %s  %.0f m from edge"
          % (report.cool_site.centroid, report.cool_site.distance_to_edge_m))
    print("  hot  site %s  %.0f m from edge"
          % (report.hot_site.centroid, report.hot_site.distance_to_edge_m))
    return 0


def backfill(args):
    """14 days x 2 sites, filter_type=3. 28 cheap parcel calls."""
    store = FixtureStore()
    if not store.exists(SELECTION_FILE):
        print("No site selection yet. Run --exceedance first.")
        return 1
    selection = store.load(SELECTION_FILE)
    api = client(refresh=args.refresh)
    dates = backfill_dates()
    print("backfilling %d days x 2 sites = %d calls" % (len(dates), 2 * len(dates)))

    for name in ("cool_site", "hot_site"):
        centre = tuple(selection[name]["centroid_lon_lat"])
        aoi = ss.parcel_around(centre)
        print("\n%s at %s" % (name, centre))
        for date in dates:
            response = api.create_heatmap(
                polygon_aoi=aoi, start_date=date.isoformat(),
                filter_type=3, granularity=100)
            result = response.get("data", response).get("result", {})
            features = result.get("map_data", {}).get("features", [])
            served = api.records[-1].served_from
            if features:
                p = features[0]["properties"]
                print("  %s  %-5s  min %.2f avg %.2f max %.2f  (%d cells)"
                      % (date, served, p["min_temperature"],
                         p["average_temperature"], p["max_temperature"], len(features)))
            else:
                print("  %s  %-5s  NO FEATURES" % (date, served))
    print("\ncache hits %d, live calls %d" % (api.cache_hits, api.live_calls))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--exceedance", action="store_true")
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--refresh", action="store_true",
                        help="bypass the cache and re-fetch")
    args = parser.parse_args()
    if args.probe:
        return probe(args)
    if args.exceedance:
        return exceedance(args)
    if args.backfill:
        return backfill(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
