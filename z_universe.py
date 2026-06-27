import requests
import pandas as pd
import time

OUTPUT_FILE = "nse_stock_master.csv"

BASE_URL = "https://www.nseindia.com"
HOME_URL = f"{BASE_URL}/"
EQUITY_QUOTE_REFERER = f"{BASE_URL}/get-quotes/equity"

session = requests.Session()

def get_nse_session(timeout: int = 30, retries: int = 3) -> requests.Session:
    """
    Initializes a requests.Session with headers and cookies to mimic a browser
    and avoid being blocked by NSE's servers.
    """
    # Start with browser-like headers for the initial page loads
    browser_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
    }
    session.headers.update(browser_headers)

    # Visit the home page and then the equity quotes page to get necessary cookies
    for attempt in range(retries):
        try:
            session.get(HOME_URL, timeout=timeout)
            session.get(EQUITY_QUOTE_REFERER, timeout=timeout)
            print("NSE session warm-up successful.")
            break  # Exit loop on success
        except requests.RequestException as e:
            print(f"Warning: Session warm-up failed on attempt {attempt + 1}/{retries}: {e}")
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))  # Exponential backoff
            else:
                print("Error: Could not establish a valid NSE session after multiple retries.")
                # The script will continue, but will likely fail on subsequent requests.

    # Update headers for API requests
    api_headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": EQUITY_QUOTE_REFERER,
        "X-Requested-With": "XMLHttpRequest",
    }
    session.headers.update(api_headers)
    
    return session


# NSE equity master list
stocks = pd.read_csv(
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
)

get_nse_session()  # Initial session warm-up
results = []

symbols = stocks["SYMBOL"].dropna().unique()

print(f"Found {len(symbols)} symbols")

for idx, symbol in enumerate(symbols, start=1):
    if idx > 1 and idx % 100 == 0:
        print(f"--- Refreshing NSE session at item {idx} ---")
        get_nse_session()

    try:
        url = f"{BASE_URL}/api/quote-equity?symbol={symbol.replace('&', '%26')}"

        r = session.get(url, timeout=30)

        if r.status_code != 200:
            print(f"Skipped {symbol}: {r.status_code}")
            continue

        data = r.json()

        info = data.get("info", {})
        sec = data.get("securityInfo", {})
        price = data.get("priceInfo", {})
        metadata = data.get("metadata", {})

        row = {
            "symbol": symbol,
            "company_name": info.get("companyName"),
            "industry": info.get("industry"),
            "sector": metadata.get("industry"),
            "market_cap": info.get("marketCap"),
            "isin": sec.get("issuedCap"),
            "face_value": sec.get("faceValue"),
            "listing_date": sec.get("listingDate"),
            "last_price": price.get("lastPrice"),
            "open": price.get("open"),
            "high": price.get("intraDayHighLow", {}).get("max"),
            "low": price.get("intraDayHighLow", {}).get("min"),
            "previous_close": price.get("previousClose"),
        }

        results.append(row)

        if idx % 50 == 0:
            print(f"{idx}/{len(symbols)} processed")

        time.sleep(0.5)

    except Exception as e:
        print(symbol, e)

df = pd.DataFrame(results)

df.to_csv(OUTPUT_FILE, index=False)

print(f"Saved {len(df)} rows to {OUTPUT_FILE}")