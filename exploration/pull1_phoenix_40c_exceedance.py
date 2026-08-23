import json
from dotenv import load_dotenv
from fortyguard import FortyGuardClient

load_dotenv()
client = FortyGuardClient()

# Metro Phoenix AOI (~384 km²)
metro_phoenix_polygon = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-112.20, 33.40],
                        [-111.95, 33.40],
                        [-111.95, 33.55],
                        [-112.20, 33.55],
                        [-112.20, 33.40]
                    ]
                ]
            }
        }
    ]
}

print("Submitting 40°C exceedance request (2026-07-26 to 2026-08-08)...")

response = client.create_heatmap(
    polygon_aoi=metro_phoenix_polygon,
    start_date="2026-07-26",
    end_date="2026-08-08",
    filter_type=4,          # Range of days (14 days = 336 hours)
    granularity=100,
    analytic_type="exceedance",
    threshold=40,
    direction="above"
)

# Extract stats_data
result = response.get("result") or response.get("data", {}).get("result", {})
stats_data = result.get("stats_data", {})
map_data = result.get("map_data", {})
features = map_data.get("features", [])

print("\n--- STATS DATA ---")
print(json.dumps(stats_data, indent=2))

# Helper to compute polygon centroid [lon, lat]
def get_centroid(coords):
    ring = coords[0]
    avg_lon = sum(pt[0] for pt in ring) / len(ring)
    avg_lat = sum(pt[1] for pt in ring) / len(ring)
    return round(avg_lon, 6), round(avg_lat, 6)

# Extract and rank cells by exceedance value (hours above 40°C)
cells = []
for f in features:
    val = f.get("properties", {}).get("value")
    if val is not None:
        geom = f.get("geometry", {}).get("coordinates", [])
        centroid = get_centroid(geom) if geom else (None, None)
        cells.append({
            "value_hours": val,
            "centroid_lon_lat": centroid,
            "coordinates": geom
        })

# Sort ascending
cells_sorted = sorted(cells, key=lambda x: x["value_hours"])

bottom_5 = cells_sorted[:5]
top_5 = cells_sorted[-5:][::-1]

print(f"\nTotal valid cells evaluated: {len(cells)}")

print("\n--- 5 LOWEST EXCEEDANCE CELLS (Coolest / Shortest Duration > 40°C) ---")
for i, c in enumerate(bottom_5, 1):
    print(f"{i}. Hours: {c['value_hours']} h | Centroid (Lon, Lat): {c['centroid_lon_lat']}")

print("\n--- 5 HIGHEST EXCEEDANCE CELLS (Hottest / Longest Duration > 40°C) ---")
for i, c in enumerate(top_5, 1):
    print(f"{i}. Hours: {c['value_hours']} h | Centroid (Lon, Lat): {c['centroid_lon_lat']}")

# Save summary to disk
output_summary = {
    "stats_data": stats_data,
    "top_5_highest_cells": top_5,
    "bottom_5_lowest_cells": bottom_5
}

with open("phoenix_40c_exceedance_sites.json", "w") as f:
    json.dump(output_summary, f, indent=2)

print("\nSaved summary and site coordinates to phoenix_40c_exceedance_sites.json")