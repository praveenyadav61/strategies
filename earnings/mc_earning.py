import requests
import pandas as pd
import time
from datetime import datetime

BASE_URL = "https://api.moneycontrol.com/mcapi/v1/earnings/rapid-results"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.moneycontrol.com/",
    "Accept": "application/json"
}

LIMIT = 100

all_rows = []

page = 1

while True:

    params = {
        "limit": LIMIT,
        "page": page,
        "type": "LR",
        "subType": "yoy",
        "category": "all",
        "sortBy": "latest",
        "indexId": "N",
        "sector": "",
        "search": "",
        "seq": "desc"
    }

    try:

        response = requests.get(
            BASE_URL,
            params=params,
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

        json_data = response.json()

        rows = json_data["data"]["list"]

        if not rows:
            print("No more pages")
            break

        print(f"Fetched page {page} | rows={len(rows)}")

        for row in rows:

            try:

                quarter_data = row[5]

                revenue = None
                gross_profit = None
                net_profit = None

                for metric in quarter_data:

                    metric_name = metric[0]

                    if metric_name == "Revenue":
                        revenue = metric[1]

                    elif metric_name == "Gross Profit":
                        gross_profit = metric[1]

                    elif metric_name == "Net Profit":
                        net_profit = metric[1]

                stock = {
                    "date": row[0],
                    "company": row[1],
                    "seo_url": row[2],
                    "ltp": row[3],
                    "change_percent": row[4],

                    "revenue": revenue,
                    "gross_profit": gross_profit,
                    "net_profit": net_profit,

                    "scid": row[6],
                    "exchange": row[7],
                    "financial_type": row[8]
                }

                all_rows.append(stock)

            except Exception as inner_error:
                print("Row parsing error:", inner_error)

        page += 1

        time.sleep(0.5)

    except Exception as e:
        print(f"Error on page {page}: {e}")
        break

# ======================================
# SAVE CSV
# ======================================

df = pd.DataFrame(all_rows)

df = df.drop_duplicates()

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

filename = f"moneycontrol_earnings_{timestamp}.csv"

df.to_csv(filename, index=False)

print("\n===================================")
print("TOTAL STOCKS:", len(df))
print("CSV SAVED:", filename)
print("===================================")

print(df.head())