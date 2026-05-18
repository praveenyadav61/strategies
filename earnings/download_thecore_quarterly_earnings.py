import os
import json
import time
import requests
from urllib.parse import quote

# Base API URL
BASE_URL = "https://earnings.thecore.in/api/dashboard?quarter={}"

# Output folder
OUTPUT_DIR = "data/quarterly/earnings"
os.makedirs(OUTPUT_DIR, exist_ok=True)

quarters = [
    # "Q1 FY09", "Q1 FY10", "Q1 FY13", "Q1 FY14", "Q1 FY15",
    # "Q1 FY16", "Q1 FY17", "Q1 FY18", "Q1 FY19", "Q1 FY20",
    # "Q1 FY21", "Q1 FY22", 
    # "Q1 FY23", "Q1 FY24", "Q1 FY25",
    # "Q1 FY26",

    # "Q2 FY09", "Q2 FY10", "Q2 FY13", "Q2 FY14", "Q2 FY15",
    # "Q2 FY16", "Q2 FY17", "Q2 FY18", "Q2 FY19", "Q2 FY20",
    # "Q2 FY21", "Q2 FY22",
    # "Q2 FY23", "Q2 FY24", "Q2 FY25",
    # "Q2 FY26",

    # "Q3 FY06", "Q3 FY07", "Q3 FY09", "Q3 FY10", "Q3 FY12",
    # "Q3 FY13", "Q3 FY14", "Q3 FY15", "Q3 FY16", "Q3 FY17",
    # "Q3 FY18", "Q3 FY19", "Q3 FY20", "Q3 FY21", "Q3 FY22",
    # "Q3 FY23", "Q3 FY24", "Q3 FY25", "Q3 FY26",

    # "Q4 FY09", "Q4 FY10", "Q4 FY12", "Q4 FY13", "Q4 FY14",
    # "Q4 FY15", "Q4 FY16", "Q4 FY17", "Q4 FY18", "Q4 FY19",
    # "Q4 FY20", "Q4 FY21", "Q4 FY22", 
    # "Q4 FY23", "Q4 FY24",
    # "Q4 FY25", 
    "Q4 FY26"
]

headers = {
    "User-Agent": "Mozilla/5.0"
}

for quarter in quarters:
    try:
        encoded_quarter = quote(quarter)
        url = BASE_URL.format(encoded_quarter)

        print(f"[INFO] Fetching {quarter}")

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()

        # File name example: Q4_FY26.json
        file_name = quarter.replace(" ", "_") + ".json"
        file_path = os.path.join(OUTPUT_DIR, file_name)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        print(f"[SUCCESS] Saved: {file_path}")

        # Small delay to avoid rate limit
        time.sleep(1)

    except Exception as e:
        print(f"[ERROR] Failed for {quarter}: {e}")

print("\n[DONE] All quarters processed.")