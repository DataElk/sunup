import os
import json
import requests
from dotenv import load_dotenv
from fortyguard import FortyGuardClient

load_dotenv()
api_key = os.getenv("FORTYGUARD_API_KEY")
base_url = os.getenv("FORTYGUARD_BASE_URL", "https://api.fortyguard.com")

print("Checking API key usage and plan tier...\n")

# Method 1: Using the Python SDK client
client = FortyGuardClient()
try:
    sdk_usage = client.fetch_api_key_usage()
    print("--- SDK fetch_api_key_usage() RESULT ---")
    print(json.dumps(sdk_usage, indent=2))
except Exception as e:
    print(f"SDK call error: {e}")

# Method 2: Direct GET call to /v1/credits for complete raw payload
headers = {
    "api-key": api_key,
    "Content-Type": "application/json"
}

resp = requests.get(f"{base_url}/v1/credits", headers=headers)
if resp.ok:
    credits_data = resp.json()
    print("\n--- DIRECT /v1/credits RESPONSE ---")
    print(json.dumps(credits_data, indent=2))

    output_path = "api_key_usage_raw.json"
    with open(output_path, "w") as f:
        json.dump(credits_data, f, indent=2)
    print(f"\nSaved raw credits data to {output_path}")
else:
    print(f"Direct request returned status {resp.status_code}: {resp.text}")