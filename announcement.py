import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import time

# -----------------------------
# CONFIG
# -----------------------------
BASE_URL = "https://www.nseindia.com"
API_URL = "https://www.nseindia.com/api/corporate-announcements"
LANDING_URL = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
INDEXES = ["equities"]
FULL_REFRESH = os.getenv("ANNOUNCEMENTS_FULL_REFRESH", "0") == "1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": LANDING_URL,
    "X-Requested-With": "XMLHttpRequest",
}

SAVE_PATH = os.path.abspath("data/Announcements/announcements.parquet")

SUBJECT_CLASSIFICATION_MAP = {
    "analysts/institutional investor meet/con. call updates": "Investor",
    "outcome of board meeting": "Board Meeting",
    "general updates": "updates",
    "updates": "updates",
    "press release": "updates",
    "investor presentation": "Investor",
    "resignation": "updates",
    "bagging/receiving of orders/contracts": "orders",
    "credit rating": "Credit Rating",
    "allotment of securities": "Bonus/Issue",
    "record date": "Bonus/Issue",
    "acquisition": "Bonus/Issue",
    "amalgamation/merger": "Merger/Demerger",
    "capacity addition": "Capacity Addition",
    "awarding of order(s)/contract(s)": "orders",
    "rights issue": "Bonus/Issue",
    "bonus": "Bonus/Issue",
    "preferential issue": "Bonus/Issue",
    "stock split": "Bonus/Issue",
    "demerger": "Merger/Demerger",
    "buyback": "Bonus/Issue",
    "public announcement - buyback of shares": "Bonus/Issue",
}

SUBJECT_CLASSIFICATION_PATTERNS = [
    ("Investor", [
        r"\banalysts?/institutional investor meet\b",
        r"\bcon\.?\s*call\b",
        r"\binvestor presentation\b",
        r"\binvestor meet\b",
        r"\binvestors?\b",
        r"\bearnings call\b",
    ]),
    ("Board Meeting", [
        r"\boutcome of board meeting\b",
        r"\bboard meeting\b",
        r"\bcommittee meeting\b",
    ]),
    ("orders", [
        r"\bbagging/receiving of orders?/contracts?\b",
        r"\bawarding of orders?/contracts?\b",
        r"\borders?/contracts?\b",
        r"\border\b",
        r"\bcontract\b",
    ]),
    ("Credit Rating", [
        r"\bcredit rating\b",
        r"\brating\b",
    ]),
    ("Bonus/Issue", [
        r"\ballotment of securities\b",
        r"\brecord date\b",
        r"\bacquisition\b",
        r"\brights issue\b",
        r"\bbonus\b",
        r"\bpreferential issue\b",
        r"\bstock split\b",
        r"\bbuyback\b",
        r"\bissue of securities\b",
        r"\boptions to purchase securities\b",
        r"\besop\b|\besos\b|\besps\b",
    ]),
    ("Merger/Demerger", [
        r"\bamalgamation\b",
        r"\bmerger\b",
        r"\bdemerger\b",
        r"\bscheme of arrangement\b",
        r"\brestructuring\b",
    ]),
    ("Capacity Addition", [
        r"\bcapacity addition\b",
        r"\bcommencement of commercial production/operations\b",
        r"\bcommercial production\b",
        r"\bcapacity\b",
    ]),
    ("updates", [
        r"\bgeneral updates\b",
        r"\bupdates\b",
        r"\bpress release\b",
        r"\bresignation\b",
        r"\bappointment\b",
        r"\bchange in management\b",
        r"\bchange in director",
        r"\bcessation\b",
        r"\bretirement\b",
        r"\bchange in auditors?\b",
        r"\bchange in company secretary/compliance officer\b",
        r"\bmonthly business updates\b",
        r"\bproduct launch\b",
        r"\bincorporation\b",
        r"\bclarification\b",
        r"\bnews verification\b",
        r"\brumour verification\b",
        r"\bdisclosure of material issue\b",
        r"\bagreements?\b",
        r"\bmemorandum of understanding/agreements\b",
        r"\bcorrigendum\b",
    ]),
]


def parse_nse_datetime(series):
    parsed = pd.to_datetime(series, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    parsed = parsed.fillna(
        pd.to_datetime(series, format="%d-%b-%Y %H:%M:%S", errors="coerce")
    )
    parsed = parsed.fillna(
        pd.to_datetime(series, format="%d%m%Y%H%M%S", errors="coerce")
    )
    return parsed


def apply_subject_classification(df):
    if df.empty or "subject" not in df.columns:
        return df

    df = df.copy()
    normalized_subject = df["subject"].astype(str).str.strip().str.lower()
    classification = normalized_subject.map(SUBJECT_CLASSIFICATION_MAP)

    for category, patterns in SUBJECT_CLASSIFICATION_PATTERNS:
        pattern_mask = pd.Series(False, index=df.index)
        for pattern in patterns:
            pattern_mask = pattern_mask | normalized_subject.str.contains(
                pattern,
                case=False,
                regex=True,
                na=False,
            )
        classification = classification.mask(classification.isna() & pattern_mask, category)

    df["classification"] = classification.fillna("Other")
    return df

# -----------------------------
# SESSION
# -----------------------------
def create_session():
    s = requests.Session()
    s.get(BASE_URL, headers=HEADERS, timeout=20)
    return s

# -----------------------------
# FETCH FUNCTION
# -----------------------------
def fetch_data(session, from_date, to_date, index_name="equities", retries=3):
    params = {
        "index": index_name,
        "from_date": from_date,
        "to_date": to_date
    }

    for i in range(retries):
        try:
            res = session.get(API_URL, headers=HEADERS, params=params, timeout=10)
            res.raise_for_status()
            data = res.json()

            if isinstance(data, list):
                return data

            print(f"Unexpected response for {index_name} {from_date} to {to_date}: {data}")
            return []
        except Exception as e:
            print(f"Retry {i+1} failed: {e}")
            time.sleep(2)

    return []

# -----------------------------
# CLEANING
# -----------------------------
def clean_data(df):
    if df.empty:
        return df

    df = df.copy()

    # normalize columns
    df.columns = df.columns.str.lower()

    # Keep both raw NSE API columns and already-normalized parquet columns.
    keep_cols = [
        "symbol",
        "desc",
        "sm_name",
        "attchmnttext",
        "seq_id",
        "hasxbrl",
        "smindustry",
        "dt",
        "an_dt",
        "sort_date",
        "attchmntfile",
        "subject",
        "company_name",
        "attachment_text",
        "industry",
        "has_xbrl",
        "date_raw",
        "announcement_datetime",
        "sort_datetime",
        "attachment_url",
        "date",
        "index_name",
    ]
    df = df[[c for c in keep_cols if c in df.columns]]

    # Rename only raw API columns that are still present.
    rename_map = {}
    if "desc" in df.columns:
        rename_map["desc"] = "subject"
    if "sm_name" in df.columns:
        rename_map["sm_name"] = "company_name"
    if "attchmnttext" in df.columns:
        rename_map["attchmnttext"] = "attachment_text"
    if "smindustry" in df.columns:
        rename_map["smindustry"] = "industry"
    if "hasxbrl" in df.columns:
        rename_map["hasxbrl"] = "has_xbrl"
    if "dt" in df.columns:
        rename_map["dt"] = "date_raw"
    if "an_dt" in df.columns:
        rename_map["an_dt"] = "announcement_datetime"
    if "sort_date" in df.columns:
        rename_map["sort_date"] = "sort_datetime"
    if "attchmntfile" in df.columns:
        rename_map["attchmntfile"] = "attachment_url"
    if rename_map:
        df.rename(columns=rename_map, inplace=True)

    # Resolve duplicate columns that can appear after concat(existing, new).
    df = df.loc[:, ~df.columns.duplicated()].copy()

    # NSE uses multiple timestamp formats across market segments.
    date_series = None
    for candidate in ["date", "sort_datetime", "announcement_datetime", "date_raw"]:
        if candidate in df.columns:
            if candidate == "date":
                parsed = pd.to_datetime(df[candidate], errors="coerce")
            else:
                parsed = parse_nse_datetime(df[candidate])
            date_series = parsed if date_series is None else date_series.fillna(parsed)

    df["date"] = date_series

    if "subject" in df.columns:
        # remove dividends
        df["subject"] = df["subject"].astype(str).str.lower()
        df = df[~df["subject"].str.contains("dividend", case=False, na=False)]

    df = apply_subject_classification(df)

    # clean text
    if "company_name" in df.columns:
        df["company_name"] = df["company_name"].astype(str).str.strip()

    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()

    if "attachment_text" in df.columns:
        df["attachment_text"] = df["attachment_text"].astype(str).str.strip()

    if "industry" in df.columns:
        df["industry"] = df["industry"].astype(str).str.strip()

    if "has_xbrl" in df.columns:
        df["has_xbrl"] = (
            pd.Series(df["has_xbrl"], dtype="boolean")
            .fillna(False)
            .astype(bool)
        )

    # drop duplicates
    df.drop_duplicates(inplace=True)
    df.dropna(subset=["date"], inplace=True)

    return df

# -----------------------------
# LOAD EXISTING DATA
# -----------------------------
def load_existing_data():
    if not os.path.exists(SAVE_PATH):
        return pd.DataFrame()

    try:
        existing_df = pd.read_parquet(SAVE_PATH)
        if "date" in existing_df.columns:
            existing_df["date"] = pd.to_datetime(existing_df["date"], errors="coerce")
        existing_df = apply_subject_classification(existing_df)
        return existing_df
    except Exception as e:
        print(f"Could not read existing parquet file: {e}")
        return pd.DataFrame()


# -----------------------------
# SAVE SINGLE PARQUET
# -----------------------------
def save_parquet(df):
    if df.empty:
        print("No data to save")
        return

    os.makedirs(os.path.dirname(SAVE_PATH), exist_ok=True)
    df.to_parquet(SAVE_PATH, index=False)
    print(f"Saved to {SAVE_PATH}")

# -----------------------------
# MAIN PIPELINE
# -----------------------------
def run_pipeline():
    session = create_session()
    existing_df = load_existing_data()

    end_date = datetime.today()

    if FULL_REFRESH:
        start_date = end_date - timedelta(days=180)
        print("Full refresh mode enabled: fetching the last 6 months.")
    elif not existing_df.empty and "date" in existing_df.columns:
        last_saved_date = existing_df["date"].max()
        if pd.notna(last_saved_date):
            # Re-fetch from the last saved calendar date so late NSE updates
            # on that day are merged back into the single parquet safely.
            start_date = last_saved_date.normalize()
        else:
            start_date = end_date - timedelta(days=180)
    else:
        start_date = end_date - timedelta(days=180)

    all_data = []

    current = start_date

    while current <= end_date:
        next_day = current + timedelta(days=1)

        print(f"Fetching {current.date()}")

        for index_name in INDEXES:
            data = fetch_data(
                session,
                current.strftime("%d-%m-%Y"),
                next_day.strftime("%d-%m-%Y"),
                index_name=index_name,
            )

            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data)
                df["index_name"] = index_name
                all_data.append(df)

        current = next_day
        time.sleep(0.5)  # avoid blocking

    if not all_data:
        if existing_df.empty:
            print("No data fetched")
        else:
            print(
                f"No new announcements found. "
                f"Existing file is already updated through {existing_df['date'].max()}."
            )
        return

    new_df = pd.concat(all_data, ignore_index=True)
    new_df = clean_data(new_df)

    if existing_df.empty:
        final_df = new_df
    else:
        final_df = pd.concat([existing_df, new_df], ignore_index=True)
        final_df = clean_data(final_df)

    final_df = final_df.sort_values("date").reset_index(drop=True)
    save_parquet(final_df)

    print("Pipeline completed")

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    run_pipeline()
