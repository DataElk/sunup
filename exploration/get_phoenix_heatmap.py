import json
from dotenv import load_dotenv
from fortyguard import FortyGuardClient

# Load API credentials from .env
load_dotenv()

client = FortyGuardClient()

# Small polygon bounding box in Downtown Phoenix, AZ
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

print("Submitting heatmap request for Phoenix polygon...")

# client.create_heatmap handles submission and polls until completion
response = client.create_heatmap(
    polygon_aoi=phoenix_polygon,
    start_date="2024-07-15",
    start_time="14:00",
    filter_type=1,      # 1 = single hour
    granularity=100     # 100m grid resolution
)

# Pretty print complete raw payload to terminal
print("\n--- COMPLETE RAW RESPONSE ---\n")
print(json.dumps(response, indent=2))

# Save directly to a JSON file so large coordinate arrays don't get truncated in CMD
with open("phoenix_heatmap_raw.json", "w") as f:
    json.dump(response, f, indent=2)

print("\nSaved full raw JSON output to phoenix_heatmap_raw.json")