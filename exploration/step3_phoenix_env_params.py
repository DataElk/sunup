import os
import time
import json
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("FORTYGUARD_API_KEY")
base_url = os.getenv("FORTYGUARD_BASE_URL", "https://api.fortyguard.com")

headers = {
    "api-key": api_key,
    "Content-Type": "application/json"
}

payload = {
    "latitude": 33.4484,
    "longitude": -112.0740,
    "temperature": 39.5,
    "date_time": {
        "start_date": "2024-07-15",
        "filter_type": 3             # 3 = Single Day (00:00 to 23:59)
    },
    "analysis": [
        "wet_bulb_temperature_celsius",
        "solar_irradiance",
        "relative_humidity_percent"
    ]
}

print("Submitting full-day environmental parameters request...")
submit_resp = requests.post(f"{base_url}/v1/env_params", headers=headers, json=payload)
submit_resp.raise_for_status()

submit_data = submit_resp.json()
print("\n--- SUBMISSION RESPONSE ---")
print(json.dumps(submit_data, indent=2))

activity_id = submit_data["data"]["activity_id"]
print(f"\nPolling activity {activity_id}...")

# Poll status endpoint until completed
while True:
    status_resp = requests.get(f"{base_url}/v1/status/{activity_id}", headers=headers)
    status_resp.raise_for_status()
    status_data = status_resp.json()
    status = status_data.get("data", {}).get("status")

    if status == "Completed":
        print("\n--- COMPLETED RESULT METADATA & ARRAY SHAPES ---")
        result = status_data["data"]["result"]
        
        # Print Metadata
        print("Metadata:", json.dumps(result.get("metadata", {}), indent=2))
        
        # Print Array lengths / shapes
        locations = result.get("locations", [])
        if locations:
            loc = locations[0]
            params = loc.get("parameters", {})
            solar = loc.get("solar_irradiance", {})
            
            print("\nParameter Array Lengths:")
            for param_name, values in params.items():
                if isinstance(values, list):
                    print(f"  - {param_name}: array of length {len(values)} (sample: {values[:3]}...)")
                else:
                    print(f"  - {param_name}: {type(values)} -> {values}")
            
            print("\nSolar Irradiance Structure:")
            print(json.dumps(solar, indent=2))

        # Save full raw response
        output_path = "phoenix_env_params_raw.json"
        with open(output_path, "w") as f:
            json.dump(status_data, f, indent=2)
        print(f"\nSaved full raw output to {output_path}")
        break

    elif status == "Failed":
        print("Task failed:", status_data)
        break

    time.sleep(3)