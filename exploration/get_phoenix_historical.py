import json
from dotenv import load_dotenv
from fortyguard import FortyGuardClient

load_dotenv()
client = FortyGuardClient()

# Identical Phoenix Downtown polygon
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

print("Submitting historical request (14 days back: 2024-07-01)...")

response = client.create_heatmap(
    polygon_aoi=phoenix_polygon,
    start_date="2024-07-01",  # 14 days prior to 2024-07-15
    start_time="14:00",
    filter_type=1,
    granularity=100
)

# Pretty print response
print("\n--- HISTORICAL RAW RESPONSE ---\n")
print(json.dumps(response, indent=2))

# Save to file for comparison
with open("phoenix_heatmap_historical_raw.json", "w") as f:
    json.dump(response, f, indent=2)

print("\nSaved output to phoenix_heatmap_historical_raw.json")