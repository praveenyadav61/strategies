import requests
import time

def fetch_index_constituents(index_name):

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.nseindia.com/",
    }

    encoded_index = index_name.replace(" ", "%20")

    url = (
        "https://www.nseindia.com/api/"
        f"equity-stockIndices?index={encoded_index}"
    )

    session = requests.Session()

    session.get(
        "https://www.nseindia.com/",
        headers=headers
    )

    response = session.get(
        url,
        headers=headers
    )

    data = response.json()

    raw_data = []

    total_ffmc = 0

    for row in data["data"]:

        ffmc = row.get("ffmc")

        symbol = row.get("symbol")

        # Skip index row itself
        if symbol == index_name:
            continue

        if ffmc is None:
            continue

        raw_data.append({
            "ticker": f"{symbol}.NS",
            "ffmc": ffmc
        })

        total_ffmc += ffmc

    constituents = {}

    for row in raw_data:

        weight = (
            row["ffmc"] / total_ffmc
        ) * 100

        constituents[row["ticker"]] = weight

    return constituents

def calculate_index_earnings(index_constituents, results_data):

    declared_companies = declared_weight = 0

    current_revenue = previous_revenue = 0
    current_profit = previous_profit = 0

    weighted_current_revenue = weighted_previous_revenue = 0
    weighted_current_profit = weighted_previous_profit = 0

    logs = []

    for ticker, weight in index_constituents.items():

        data = results_data.get(ticker)
        if not data:
            continue

        declared_companies += 1
        declared_weight += weight

        revenue = data.get("revenue")
        profit = data.get("net_profit")

        revenue_yoy = data.get("revenue_yoy")
        profit_yoy = data.get("profit_yoy")

        if revenue and revenue_yoy is not None and revenue_yoy != -1:

            prev_revenue = revenue / (1 + revenue_yoy)

            current_revenue += revenue
            previous_revenue += prev_revenue

            weighted_current_revenue += revenue * weight
            weighted_previous_revenue += prev_revenue * weight

        if profit and profit_yoy is not None and profit_yoy != -1:

            prev_profit = profit / (1 + profit_yoy)

            current_profit += profit
            previous_profit += prev_profit

            weighted_current_profit += profit * weight
            weighted_previous_profit += prev_profit * weight

        log_msg = f"Processed {ticker}: {revenue},{prev_revenue}, {profit},{prev_profit}"
        print(log_msg)
        logs.append(log_msg)

    normal_revenue_growth = (
        ((current_revenue - previous_revenue) / previous_revenue) * 100
        if previous_revenue else None
    )

    normal_profit_growth = (
        ((current_profit - previous_profit) / previous_profit) * 100
        if previous_profit else None
    )

    weighted_revenue_growth = (
        (
            (weighted_current_revenue - weighted_previous_revenue)
            / weighted_previous_revenue
        ) * 100
        if weighted_previous_revenue else None
    )

    weighted_profit_growth = (
        (
            (weighted_current_profit - weighted_previous_profit)
            / weighted_previous_profit
        ) * 100
        if weighted_previous_profit else None
    )

    return {
        "declared_companies": declared_companies,
        "total_companies": len(index_constituents),
        "declared_weight_pct": round(declared_weight, 2),

        "current_revenue": round(current_revenue),
        "previous_revenue": round(previous_revenue),

        "current_profit": round(current_profit),
        "previous_profit": round(previous_profit),

        "normal_revenue_growth_pct": (
            round(normal_revenue_growth, 2)
            if normal_revenue_growth is not None else None
        ),

        "normal_profit_growth_pct": (
            round(normal_profit_growth, 2)
            if normal_profit_growth is not None else None
        ),

        "weighted_revenue_growth_pct": (
            round(weighted_revenue_growth, 2)
            if weighted_revenue_growth is not None else None
        ),

        "weighted_profit_growth_pct": (
            round(weighted_profit_growth, 2)
            if weighted_profit_growth is not None else None
        ),
        "logs": logs
    }

def print_summary(
    index_name,
    result
):

    print(f"\n===== {index_name} =====\n")

    for k, v in result.items():
        print(f"{k}: {v}")

def has_value(x):
    return x is not None and x != ""

def fetch_earnings_data(quarter):
    API_BASE_URL = "https://earnings.thecore.in/api/dashboard"
    TIMEOUT = 30
    url = f"{API_BASE_URL}?quarter={quarter.replace(' ', '%20')}"
    response = requests.get(url, timeout=TIMEOUT)
    response.raise_for_status()

    payload = response.json()
    return payload.get("data", {}).get("rows", [])

def build_ticker_map(rows):
    ticker_map = {}
    for row in rows:
        if not (has_value(row.get("revenue")) and has_value(row.get("operating_profit"))):
            continue

        ticker = row.get("ticker")
        if not ticker:
            continue

        ticker_map[ticker] = {
            "company_name": row.get("company_name"),
            "revenue": row.get("revenue"),
            "operating_profit": row.get("operating_profit"),
            "net_profit": row.get("net_profit"),
            "eps": row.get("eps"),
            "revenue_qoq": row.get("revenue_qoq"),
            "revenue_yoy": row.get("revenue_yoy"),
            "profit_qoq": row.get("profit_qoq"),
            "profit_yoy": row.get("profit_yoy")
        }
    return ticker_map

def main():
    quarter = "Q4 FY26"
    rows = fetch_earnings_data(quarter)
    earnings_data = build_ticker_map(rows)    
    index_name = "NIFTY 50"
    index_constituents = fetch_index_constituents(index_name)
    result = calculate_index_earnings(index_constituents,earnings_data)
    print_summary(index_name,result)
    
    # Save logs to txt file
    if "logs" in result and result["logs"]:
        with open("ticker_logs.txt", "w") as f:
            f.write("\n".join(result["logs"]))
        print(f"\nLogs saved to ticker_logs.txt ({len(result['logs'])} entries)")
    # for k, v in list(index_constituents.items())[:5]:
    #     print(k, round(v, 2))

if __name__ == "__main__":
    main()