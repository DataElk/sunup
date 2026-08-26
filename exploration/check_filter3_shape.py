import json
from dotenv import load_dotenv
from fortyguard import FortyGuardClient

load_dotenv()
client = FortyGuardClient()

# Small parcel bounding box in Downtown Phoenix
phoenix_parcel = {
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

print("Submitting single-day heatmap request (filter_type=3)...")

response = client.create_heatmap(
    polygon_aoi=phoenix_parcel,
    start_date="2024-07-15",
    filter_type=3,          # Single Day (covers 00:00 - 23:59)
    granularity=100
)

# Extract and inspect stats
stats = response.get("result", {}).get("stats_data") or response.get("data", {}).get("result", {}).get("stats_data", {})
print("\n--- STATS DATA ---")
print(json.dumps(stats, indent=2))

# Inspect features
features = response.get("result", {}).get("map_data", {}).get("features") or \
           response.get("data", {}).get("result", {}).get("map_data", {}).get("features", [])

print(f"\nTotal cell features returned: {len(features)}")
if features:
    sample_props = features[0].get("properties", {})
    print("\n--- SAMPLE CELL PROPERTIES ---")
    print(json.dumps(sample_props, indent=2))
    
    # filter_type=3 was expected to return hourly arrays; it returns scalars.
    for k, v in sample_props.items():
        if isinstance(v, list):
            print(f"  Field '{k}' is an ARRAY of length {len(v)}")
        else:
            print(f"  Field '{k}' is a SCALAR: {v}")

# Save full raw response to file
output_path = "phoenix_singleday_filter3_raw.json"
with open(output_path, "w") as f:
    json.dump(response, f, indent=2)

print(f"\nSaved full raw output to {output_path}")