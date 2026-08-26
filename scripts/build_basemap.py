"""Derive a tiny offline basemap for the Map view.

    python scripts/build_basemap.py            # use the cached Overpass response
    python scripts/build_basemap.py --fetch    # re-fetch from Overpass first

WHY THIS EXISTS
---------------
The exceedance choropleth was two dots 20 km apart on a field of red. Nobody
who knows Phoenix could locate either site, which makes the site-selection
claim unauditable: you cannot check a spatial result you cannot place.

WHY IT IS STILL OFFLINE
-----------------------
This is a BUILD-time fetch, cached to a static JS module, exactly like every
other fixture in this project. The demo itself makes zero network calls
(SPEC.md hard constraint 6). No tile server is contacted at render time --
there are no tiles, only ~2 000 simplified polylines drawn on the same canvas.

WHAT IS DELIBERATELY OMITTED
----------------------------
Everything except motorways, trunk and primary roads, the Salt River, and
parks above 4 ha. A basemap here is a locator, not a subject. It is drawn in
--map-* neutrals underneath the choropleth so it never competes with the data.

Source: OpenStreetMap contributors, ODbL 1.0. Attribution is rendered in the
map legend, which the licence requires and which is also just honest.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from acclimate import siteselection as ss  # noqa: E402
from acclimate.sources.fixtures import FixtureStore  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "data", "osm_basemap_raw.json")
OUT = os.path.join(HERE, "..", "app", "data", "basemap.js")

OVERPASS = "https://overpass-api.de/api/interpreter"

# Simplification budget. The choropleth underneath has no structure below about
# 2 km (see scripts/build_map_data.py), so a basemap resolved to 60 m is already
# far finer than anything it sits on top of.
TOLERANCE_M = 40.0
# Zero, deliberately. OSM splits one continuous arterial into many short ways
# at intersections and attribute changes, so a length filter punches visible
# gaps into roads that are physically continuous.
MIN_ROAD_LENGTH_M = 0.0
MIN_PARK_AREA_M2 = 40_000.0

ROAD_CLASS = {"motorway": 1, "trunk": 1, "primary": 2}


def query(west: float, south: float, east: float, north: float) -> str:
    bbox = "%f,%f,%f,%f" % (south, west, north, east)
    return (
        "[out:json][timeout:90];\n"
        "(\n"
        '  way["highway"~"^(motorway|trunk|primary)$"](%s);\n'
        '  way["waterway"="river"](%s);\n'
        '  way["leisure"="park"](%s);\n'
        ");\n"
        "out geom;" % (bbox, bbox, bbox)
    )


def fetch(west, south, east, north) -> dict:
    body = urllib.parse.urlencode({"data": query(west, south, east, north)})
    request = urllib.request.Request(
        OVERPASS, data=body.encode("utf-8"),
        headers={"User-Agent": "acclimate-basemap/1.0 (hackathon build script)"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def metres_per_degree(lat: float):
    return 111_320.0 * math.cos(math.radians(lat)), 110_570.0


def simplify(points, tolerance_m, mx, my):
    """Douglas-Peucker in local metres. Plain recursion; the ways are short."""
    if len(points) < 3:
        return points

    def perpendicular(p, a, b):
        ax, ay = (a[0] - p[0]) * mx, (a[1] - p[1]) * my
        bx, by = (b[0] - p[0]) * mx, (b[1] - p[1]) * my
        dx, dy = bx - ax, by - ay
        span = math.hypot(dx, dy)
        if span == 0:
            return math.hypot(ax, ay)
        return abs(ax * dy - ay * dx) / span

    worst, index = 0.0, 0
    for i in range(1, len(points) - 1):
        d = perpendicular(points[i], points[0], points[-1])
        if d > worst:
            worst, index = d, i
    if worst <= tolerance_m:
        return [points[0], points[-1]]
    left = simplify(points[:index + 1], tolerance_m, mx, my)
    right = simplify(points[index:], tolerance_m, mx, my)
    return left[:-1] + right


def length_m(points, mx, my):
    return sum(math.hypot((points[i + 1][0] - points[i][0]) * mx,
                          (points[i + 1][1] - points[i][1]) * my)
               for i in range(len(points) - 1))


def area_m2(points, mx, my):
    total = 0.0
    for i in range(len(points)):
        x1, y1 = points[i][0] * mx, points[i][1] * my
        x2, y2 = points[(i + 1) % len(points)][0] * mx, points[(i + 1) % len(points)][1] * my
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def clip(points, west, south, east, north):
    """Keep ways that touch the AOI at all; drawing is clipped by the canvas."""
    return any(west <= x <= east and south <= y <= north for x, y in points)


def encode(points, west, north, span_x, span_y):
    """Normalised 0..1 within the AOI, 4 decimals, about 2.5 m here.

    Normalising at build time means the renderer needs no projection code and
    the payload carries no repeated leading digits."""
    out = []
    for x, y in points:
        out.append(round((x - west) / span_x, 4))
        out.append(round((north - y) / span_y, 4))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true",
                        help="re-fetch from Overpass instead of using the cache")
    args = parser.parse_args()

    selection = FixtureStore().load("site_selection/phoenix_40c_selection.json")
    west, south, east, north = ss.bbox_of(ss.ring_of(selection["aoi_buffered"]))

    if args.fetch or not os.path.exists(RAW):
        print("fetching from Overpass ...")
        doc = fetch(west, south, east, north)
        os.makedirs(os.path.dirname(RAW), exist_ok=True)
        with open(RAW, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        print("cached %s (%.1f MB)" % (os.path.relpath(RAW), os.path.getsize(RAW) / 1e6))
    else:
        with open(RAW, "r", encoding="utf-8") as fh:
            doc = json.load(fh)

    mx, my = metres_per_degree((south + north) / 2.0)
    span_x, span_y = east - west, north - south

    roads, river, parks = [], [], []
    for element in doc.get("elements", []):
        geometry = element.get("geometry")
        if not geometry:
            continue
        points = [(p["lon"], p["lat"]) for p in geometry]
        if not clip(points, west, south, east, north):
            continue
        tags = element.get("tags", {})

        if tags.get("leisure") == "park":
            if len(points) < 4 or area_m2(points, mx, my) < MIN_PARK_AREA_M2:
                continue
            simplified = simplify(points, TOLERANCE_M * 2, mx, my)
            if len(simplified) >= 4:
                parks.append(encode(simplified, west, north, span_x, span_y))
            continue

        if tags.get("waterway") == "river":
            simplified = simplify(points, TOLERANCE_M, mx, my)
            river.append(encode(simplified, west, north, span_x, span_y))
            continue

        klass = ROAD_CLASS.get(tags.get("highway"))
        if klass is None or length_m(points, mx, my) < MIN_ROAD_LENGTH_M:
            continue
        simplified = simplify(points, TOLERANCE_M, mx, my)
        if len(simplified) >= 2:
            roads.append([klass] + encode(simplified, west, north, span_x, span_y))

    payload = {
        "attribution": "(c) OpenStreetMap contributors, ODbL 1.0",
        "retrieved": doc.get("osm3s", {}).get("timestamp_osm_base", "unknown"),
        "bounds": {"west": west, "south": south, "east": east, "north": north},
        "note": ("Normalised 0..1 within the AOI bounds. Roads carry a leading "
                 "class: 1 = motorway/trunk, 2 = primary."),
        "roads": roads,
        "river": river,
        "parks": parks,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("/* Generated by scripts/build_basemap.py, do not edit.\n"
                 "   OpenStreetMap contributors, ODbL 1.0. Build-time fetch, cached\n"
                 "   here so the demo makes no network calls. */\n")
        fh.write("window.BASEMAP = ")
        json.dump(payload, fh, separators=(",", ":"))
        fh.write(";\n")

    points = sum((len(r) - 1) // 2 for r in roads)
    print("wrote %s (%d KB)" % (os.path.relpath(OUT), os.path.getsize(OUT) // 1024))
    print("  %d roads (%d points), %d river ways, %d parks >= %.0f ha"
          % (len(roads), points, len(river), len(parks), MIN_PARK_AREA_M2 / 10_000))


if __name__ == "__main__":
    main()
