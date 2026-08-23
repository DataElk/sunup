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

thresholds = [34, 36, 38, 40, 42]
sweep_results = {}

print("Running threshold sweep (34°C, 36°C, 38°C, 40°C, 42°C)...")

for t in thresholds:
    print(f"\nSubmitting exceedance heatmap for threshold = {t}°C...")
    resp = client.create_heatmap(
        polygon_aoi=phoenix_citywide_polygon,
        start_date="2024-07-01",
        end_date="2024-07-07",
        filter_type=4,          # Range of days
        granularity=100,
        analytic_type="exceedance",
        threshold=t,
        direction="above"
    )
    
    # Extract stats_data directly
    stats = resp.get("result", {}).get("stats_data") or resp.get("data", {}).get("result", {}).get("stats_data", {})
    sweep_results[f"{t}C"] = stats
    print(f"Stats for {t}°C: {json.dumps(stats)}")

# Print clean comparison table
print("\n" + "="*70)
print(f"{'Threshold':<12} | {'Min (hrs)':<10} | {'Max (hrs)':<10} | {'Mean (hrs)':<12} | {'Std Dev':<10}")
print("="*70)

for t in thresholds:
    st = sweep_results.get(f"{t}C", {})
    temp_stats = st.get("temperature_stats", st)
    
    min_val = temp_stats.get("min", temp_stats.get("minimum", "N/A"))
    max_val = temp_stats.get("max", temp_stats.get("maximum", "N/A"))
    mean_val = temp_stats.get("avg", temp_stats.get("mean", "N/A"))
    std_val = temp_stats.get("std", temp_stats.get("standard_deviation", "N/A"))
    
    print(f"{t:>3} °C        | {str(min_val):<10} | {str(max_val):<10} | {str(mean_val):<12} | {str(std_val):<10}")

print("="*70)

with open("phoenix_threshold_sweep_summary.json", "w") as f:
    json.dump(sweep_results, f, indent=2)

print("\nSaved sweep summary to phoenix_threshold_sweep_summary.json")