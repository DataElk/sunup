import json
from dotenv import load_dotenv
from fortyguard import FortyGuardClient

load_dotenv()
client = FortyGuardClient()

# Downtown Phoenix polygon
phoenix_polygon = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-112.0790, 33.4450],
                        [-112.0690, 33.4450],
                        [-112.0690, 33.4550],
                        [-112.0790, 33.4550],
                        [-112.0790, 33.4450]
                    ]
                ]
            }
        }
    ]
}

print("Submitting recent heatmap request for 2026-08-09...")

response = client.create_heatmap(
    polygon_aoi=phoenix_polygon,
    start_date="2026-08-09",
    start_time="14:00",
    filter_type=1,      # Single hour
    granularity=100
)

# Output summary stats
stats = response.get("result", {}).get("stats_data", {})
print("\n--- RECENT STATS DATA ---")
print(json.dumps(stats, indent=2))

# Inspect sample tile properties
features = response.get("result", {}).get("map_data", {}).get("features", [])
if features:
    print("\n--- SAMPLE CELL PROPERTIES ---")
    print(json.dumps(features[0].get("properties", {}), indent=2))

# Save the full raw response
output_path = "phoenix_heatmap_recent_raw.json"
with open(output_path, "w") as f:
    json.dump(response, f, indent=2)

print(f"\nSaved full raw output to {output_path}")