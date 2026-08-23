import json
from dotenv import load_dotenv
from fortyguard import FortyGuardClient

load_dotenv()
client = FortyGuardClient()

# Downtown Phoenix parcel
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

dates = [
    "2026-08-05",
    "2026-08-06",
    "2026-08-07",
    "2026-08-08",
    "2026-08-09"
]

daily_progression = {}

print("Running 5-day progression query (2026-08-05 to 2026-08-09)...")

for d in dates:
    print(f"\nSubmitting single-day heatmap for {d} (filter_type=3)...")
    resp = client.create_heatmap(
        polygon_aoi=phoenix_parcel,
        start_date=d,
        filter_type=3,      # Single full day
        granularity=100
    )
    
    result = resp.get("result") or resp.get("data", {}).get("result", {})
    stats = result.get("stats_data", {})
    daily_progression[d] = stats

# Display formatted daily progression table
print("\n" + "="*68)
print(f"{'Date':<14} | {'Min (°C)':<10} | {'Max (°C)':<10} | {'Mean (°C)':<12} | {'Std Dev':<10}")
print("="*68)

for d in dates:
    st = daily_progression.get(d, {})
    temp_stats = st.get("temperature_stats", st)
    
    min_val = temp_stats.get("min", temp_stats.get("minimum", "N/A"))
    max_val = temp_stats.get("max", temp_stats.get("maximum", "N/A"))
    mean_val = temp_stats.get("avg", temp_stats.get("mean", "N/A"))
    std_val = temp_stats.get("std", temp_stats.get("standard_deviation", "N/A"))
    
    print(f"{d:<14} | {str(min_val):<10} | {str(max_val):<10} | {str(mean_val):<12} | {str(std_val):<10}")

print("="*68)

output_file = "phoenix_5day_daily_stats.json"
with open(output_file, "w") as f:
    json.dump(daily_progression, f, indent=2)

print(f"\nSaved 5-day daily statistics to {output_file}")