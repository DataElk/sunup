import json
from dotenv import load_dotenv
from fortyguard import FortyGuardClient

load_dotenv()
client = FortyGuardClient()

# Citywide Phoenix bounding box (~100 km²)
phoenix_citywide_polygon = {
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

print("Submitting citywide Phoenix exceedance heatmap (7-day window)...")

response = client.create_heatmap(
    polygon_aoi=phoenix_citywide_polygon,
    start_date="2024-07-01",
    end_date="2024-07-07",
    filter_type=4,          # Range of days
    granularity=100,
    analytic_type="exceedance",
    threshold=30,
    direction="above"
)

# Output summary stats
stats = response.get("result", {}).get("stats_data", {})
print("\n--- STATS DATA ---")
print(json.dumps(stats, indent=2))

# Inspect the first tile properties to verify the value field name
features = response.get("result", {}).get("map_data", {}).get("features", [])
if features:
    print("\n--- SAMPLE CELL PROPERTIES ---")
    print(json.dumps(features[0].get("properties", {}), indent=2))
    print(f"Total tiles returned: {len(features)}")

# Save the full raw response
output_path = "phoenix_exceedance_7day_raw.json"
with open(output_path, "w") as f:
    json.dump(response, f, indent=2)

print(f"\nSaved full raw output to {output_path}")