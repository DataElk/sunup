import os
import time
import json
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("FORTYGUARD_API_KEY")
base_url = os.getenv("FORTYGUARD_BASE_URL", "https://api.fortyguard.com")

headers = {"api-key": api_key, "Content-Type": "application/json"}

# 1. Submit Satellite Segmentation Request
payload = {
    "sat": {
        "latitude": 33.4484,
        "longitude": -112.0740
    },
    "date_time": {
        "start_date": "2024-07-15",
        "start_time": "14:00",
        "filter_type": 1
    },
    "granularity": 100
}

submit_resp = requests.post(f"{base_url}/v1/satellite", headers=headers, json=payload)
submit_data = submit_resp.json()
activity_id = submit_data["data"]["activity_id"]
print(f"Submitted task: {activity_id}. Polling for result...")

# 2. Poll Status Endpoint Until Completed
while True:
    status_resp = requests.get(f"{base_url}/v1/status/{activity_id}", headers=headers)
    status_data = status_resp.json()
    status = status_data.get("data", {}).get("status")

    if status == "Completed":
        result = status_data["data"]["result"]
        segmentation = result.get("segmentation", {})
        
        print("\n--- EXACT LAND-COVER CLASSES (SEGMENTS) ---")
        print(json.dumps(segmentation.get("segments", {}), indent=2))
        
        print("\n--- EXACT LEGEND CLASSES (IMAGE_LEGEND) ---")
        print(json.dumps(segmentation.get("image_legend", {}), indent=2))
        break
    elif status == "Failed":
        print("Task failed:", status_data)
        break

    time.sleep(3)