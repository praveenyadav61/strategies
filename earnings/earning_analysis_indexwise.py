import pandas as pd
from pathlib import Path
from datetime import datetime
import time
import requests

# =========================================================
# CONFIG
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data" / "quarterly"

AGG_CSV = DATA_DIR / "earnings_12q_aggregated.csv"

INDEX_NAMES = [
    "NIFTY 50",
    "NIFTY MIDCAP 100",
    "NIFTY SMALLCAP 100",
]
REQUEST_TIMEOUT = 60
REQUEST_RETRIES = 3
REQUEST_BACKOFF_SECONDS = 1.5

# =========================================================
# FETCH INDEX CONSTITUENTS
# =========================================================


def fetch_index_constituents(index_name):
    """
    Fetch index constituents from NSE API
    """
    print(f"[INFO] Fetching {index_name} constituents from NSE")

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

    last_error = None

    for attempt in range(1, REQUEST_RETRIES + 1):
        session = None
        try:
            session = requests.Session()

            session.get(
                "https://www.nseindia.com/",
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )

            response = session.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            raw_data = []
            total_ffmc = 0

            for row in data["data"]:
                ffmc = row.get("ffmc")
                symbol = row.get("symbol")

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
            if total_ffmc:
                for row in raw_data:
                    constituents[row["ticker"]] = row["ffmc"] / total_ffmc

            print(f"[INFO] Fetched {len(constituents)} constituents for {index_name}")
            return constituents

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_error = exc
            if attempt == REQUEST_RETRIES:
                raise
            print(
                f"[WARN] NSE fetch attempt {attempt}/{REQUEST_RETRIES} failed for {index_name}: {exc}. Retrying..."
            )
            time.sleep(REQUEST_BACKOFF_SECONDS * attempt)
        finally:
            if session is not None:
                session.close()

    if last_error is not None:
        raise last_error

    raise RuntimeError(f"Failed to fetch constituents for {index_name}")


def load_earnings_data():
    """Load the aggregated earnings CSV"""
    print(f"[INFO] Loading earnings data from {AGG_CSV}")
    df = pd.read_csv(AGG_CSV)
    print(f"[INFO] Total rows: {len(df)}")
    return df


def parse_quarter_label(label):
    """Parse an earnings quarter label like 'Q4 FY26'."""
    if not isinstance(label, str):
        return None

    import re

    match = re.search(r"Q\s*([1-4])\s*FY\s*(\d{2,4})", label, re.IGNORECASE)
    if not match:
        return None

    quarter = int(match.group(1))
    year = int(match.group(2))
    if year < 100:
        year += 2000
    return quarter, year


def quarter_sort_key(label):
    parsed = parse_quarter_label(label)
    if parsed is None:
        return 0
    quarter, year = parsed
    return year * 10 + quarter


def quarter_label_to_suffix(label):
    """Convert a quarter label like 'Q4 FY25' into a safe suffix like 'q4_fy25'."""
    if not isinstance(label, str):
        return None
    return label.strip().lower().replace(" ", "_")


def get_latest_quarter_label(df):
    labels = [
        label for label in df["quarter_label"].dropna().unique()
        if parse_quarter_label(label) is not None
    ]
    if not labels:
        return None
    return max(labels, key=quarter_sort_key)


def get_previous_quarters(current_quarter):
    parsed = parse_quarter_label(current_quarter)
    if parsed is None:
        return None, None

    quarter, year = parsed
    prev_yoy_year = year - 1
    prev_yoy = f"Q{quarter} FY{prev_yoy_year % 100:02d}"

    if quarter > 1:
        prev_qoq_quarter = quarter - 1
        prev_qoq_year = year
    else:
        prev_qoq_quarter = 4
        prev_qoq_year = year - 1
    prev_qoq = f"Q{prev_qoq_quarter} FY{prev_qoq_year % 100:02d}"

    return prev_yoy, prev_qoq


# =========================================================
# FILTER DECLARED RESULTS
# =========================================================


def get_declared_current_quarter(df, index_constituents, index_name, current_quarter):
    """
    Filter current quarter data where revenue and net_profit are not null
    and ticker is in the index.
    """
    declared = df[
        (df["quarter_label"] == current_quarter) &
        (df["revenue"].notna()) &
        (df["net_profit"].notna()) &
        (df["ticker"].isin(index_constituents.keys()))
    ].copy()

    declared["weight"] = declared["ticker"].map(index_constituents).fillna(0)

    print(f"[INFO] {current_quarter} {index_name} Declared companies: {len(declared)}")
    return declared


# =========================================================
# GET YOY COMPARISON DATA
# =========================================================


def get_previous_quarter_data(df, quarter_label, suffix):
    """
    Get previous quarter data for comparison.
    suffix: e.g. "q4_fy25" for YoY or "q3_fy26" for QoQ.
    """
    prev_data = df[
        (df["quarter_label"] == quarter_label) &
        (df["revenue"].notna()) &
        (df["net_profit"].notna())
    ].copy()

    columns = ["ticker", "revenue", "net_profit"]
    if "operating_profit" in prev_data.columns:
        columns.append("operating_profit")

    prev_data = prev_data[columns].rename(columns={
        "revenue": f"revenue_{suffix}",
        "net_profit": f"net_profit_{suffix}",
        "operating_profit": f"operating_profit_{suffix}"
    })

    print(f"[INFO] {quarter_label} companies with data: {len(prev_data)}")
    return prev_data


# =========================================================
# MERGE AND CALCULATE YOY
# =========================================================
# =========================================================


def calculate_growth_metrics(declared_df, prev_yoy_df, prev_qoq_df, prev_yoy_suffix, prev_qoq_suffix):
    """
    Merge current quarter data with YoY and QoQ comparison data.
    """
    merged = declared_df.merge(prev_yoy_df, on="ticker", how="left")
    merged = merged.merge(prev_qoq_df, on="ticker", how="left")
    merged["weight"] = merged["weight"].fillna(0)

    yoy_revenue_col = f"revenue_{prev_yoy_suffix}"
    yoy_profit_col = f"net_profit_{prev_yoy_suffix}"
    yoy_op_col = f"operating_profit_{prev_yoy_suffix}"
    qoq_revenue_col = f"revenue_{prev_qoq_suffix}"
    qoq_profit_col = f"net_profit_{prev_qoq_suffix}"
    qoq_op_col = f"operating_profit_{prev_qoq_suffix}"

    merged["revenue_yoy_growth"] = None
    merged["profit_yoy_growth"] = None
    merged["operating_profit_yoy_growth"] = None
    merged["revenue_qoq_growth"] = None
    merged["profit_qoq_growth"] = None
    merged["operating_profit_qoq_growth"] = None

    valid_revenue_yoy = merged[yoy_revenue_col].notna() & (merged[yoy_revenue_col] > 0)
    merged.loc[valid_revenue_yoy, "revenue_yoy_growth"] = (
        ((merged.loc[valid_revenue_yoy, "revenue"] - merged.loc[valid_revenue_yoy, yoy_revenue_col])
         / merged.loc[valid_revenue_yoy, yoy_revenue_col]) * 100
    )

    valid_profit_yoy = merged[yoy_profit_col].notna() & (merged[yoy_profit_col] > 0)
    merged.loc[valid_profit_yoy, "profit_yoy_growth"] = (
        ((merged.loc[valid_profit_yoy, "net_profit"] - merged.loc[valid_profit_yoy, yoy_profit_col])
         / merged.loc[valid_profit_yoy, yoy_profit_col]) * 100
    )

    valid_op_yoy = pd.Series(False, index=merged.index)
    if yoy_op_col in merged:
        valid_op_yoy = merged[yoy_op_col].notna() & (merged[yoy_op_col] > 0)
        merged.loc[valid_op_yoy, "operating_profit_yoy_growth"] = (
            ((merged.loc[valid_op_yoy, "operating_profit"] - merged.loc[valid_op_yoy, yoy_op_col])
             / merged.loc[valid_op_yoy, yoy_op_col]) * 100
        )

    valid_revenue_qoq = merged[qoq_revenue_col].notna() & (merged[qoq_revenue_col] > 0)
    merged.loc[valid_revenue_qoq, "revenue_qoq_growth"] = (
        ((merged.loc[valid_revenue_qoq, "revenue"] - merged.loc[valid_revenue_qoq, qoq_revenue_col])
         / merged.loc[valid_revenue_qoq, qoq_revenue_col]) * 100
    )

    valid_profit_qoq = merged[qoq_profit_col].notna() & (merged[qoq_profit_col] > 0)
    merged.loc[valid_profit_qoq, "profit_qoq_growth"] = (
        ((merged.loc[valid_profit_qoq, "net_profit"] - merged.loc[valid_profit_qoq, qoq_profit_col])
         / merged.loc[valid_profit_qoq, qoq_profit_col]) * 100
    )

    valid_op_qoq = pd.Series(False, index=merged.index)
    if qoq_op_col in merged:
        valid_op_qoq = merged[qoq_op_col].notna() & (merged[qoq_op_col] > 0)
        merged.loc[valid_op_qoq, "operating_profit_qoq_growth"] = (
            ((merged.loc[valid_op_qoq, "operating_profit"] - merged.loc[valid_op_qoq, qoq_op_col])
             / merged.loc[valid_op_qoq, qoq_op_col]) * 100
        )

    merged["weighted_revenue"] = merged["revenue"] * merged["weight"]
    merged[f"weighted_revenue_{prev_yoy_suffix}"] = merged[yoy_revenue_col] * merged["weight"]
    merged[f"weighted_revenue_{prev_qoq_suffix}"] = merged[qoq_revenue_col] * merged["weight"]
    merged["weighted_profit"] = merged["net_profit"] * merged["weight"]
    merged[f"weighted_profit_{prev_yoy_suffix}"] = merged[yoy_profit_col] * merged["weight"]
    merged[f"weighted_profit_{prev_qoq_suffix}"] = merged[qoq_profit_col] * merged["weight"]
    if "operating_profit" in merged:
        merged["weighted_operating_profit"] = merged["operating_profit"] * merged["weight"]
    if yoy_op_col in merged:
        merged[f"weighted_operating_profit_{prev_yoy_suffix}"] = merged[yoy_op_col] * merged["weight"]
    if qoq_op_col in merged:
        merged[f"weighted_operating_profit_{prev_qoq_suffix}"] = merged[qoq_op_col] * merged["weight"]

    summary = {
        "declared_count": len(merged),
        "declared_weight_pct": merged["weight"].sum() * 100,

        "normal_revenue_yoy_growth_pct": None,
        "weighted_revenue_yoy_growth_pct": None,
        "normal_profit_yoy_growth_pct": None,
        "weighted_profit_yoy_growth_pct": None,
        "normal_operating_profit_yoy_growth_pct": None,
        "weighted_operating_profit_yoy_growth_pct": None,

        "normal_revenue_qoq_growth_pct": None,
        "weighted_revenue_qoq_growth_pct": None,
        "normal_profit_qoq_growth_pct": None,
        "weighted_profit_qoq_growth_pct": None,
        "normal_operating_profit_qoq_growth_pct": None,
        "weighted_operating_profit_qoq_growth_pct": None,
    }

    total_revenue = merged.loc[valid_revenue_yoy, "revenue"].sum()
    total_revenue_yoy = merged.loc[valid_revenue_yoy, yoy_revenue_col].sum()
    total_weighted_revenue = merged.loc[valid_revenue_yoy, "weighted_revenue"].sum()
    total_weighted_revenue_yoy = merged.loc[valid_revenue_yoy, f"weighted_revenue_{prev_yoy_suffix}"].sum()

    if total_revenue_yoy != 0:
        summary["normal_revenue_yoy_growth_pct"] = (
            ((total_revenue - total_revenue_yoy) / total_revenue_yoy) * 100
        )
    if total_weighted_revenue_yoy != 0:
        summary["weighted_revenue_yoy_growth_pct"] = (
            ((total_weighted_revenue - total_weighted_revenue_yoy) / total_weighted_revenue_yoy) * 100
        )

    total_profit = merged.loc[valid_profit_yoy, "net_profit"].sum()
    total_profit_yoy = merged.loc[valid_profit_yoy, yoy_profit_col].sum()
    total_weighted_profit = merged.loc[valid_profit_yoy, "weighted_profit"].sum()
    total_weighted_profit_yoy = merged.loc[valid_profit_yoy, f"weighted_profit_{prev_yoy_suffix}"].sum()

    if total_profit_yoy != 0:
        summary["normal_profit_yoy_growth_pct"] = (
            ((total_profit - total_profit_yoy) / total_profit_yoy) * 100
        )
    if total_weighted_profit_yoy != 0:
        summary["weighted_profit_yoy_growth_pct"] = (
            ((total_weighted_profit - total_weighted_profit_yoy) / total_weighted_profit_yoy) * 100
        )

    if yoy_op_col in merged:
        total_op = merged.loc[valid_op_yoy, "operating_profit"].sum()
        total_op_yoy = merged.loc[valid_op_yoy, yoy_op_col].sum()
        total_weighted_op = merged.loc[valid_op_yoy, "weighted_operating_profit"].sum()
        total_weighted_op_yoy = merged.loc[valid_op_yoy, f"weighted_operating_profit_{prev_yoy_suffix}"].sum()
        if total_op_yoy != 0:
            summary["normal_operating_profit_yoy_growth_pct"] = (
                ((total_op - total_op_yoy) / total_op_yoy) * 100
            )
        if total_weighted_op_yoy != 0:
            summary["weighted_operating_profit_yoy_growth_pct"] = (
                ((total_weighted_op - total_weighted_op_yoy) / total_weighted_op_yoy) * 100
            )

    total_revenue_qoq = merged.loc[valid_revenue_qoq, "revenue"].sum()
    total_revenue_qoq_prev = merged.loc[valid_revenue_qoq, qoq_revenue_col].sum()
    total_weighted_revenue_qoq = merged.loc[valid_revenue_qoq, "weighted_revenue"].sum()
    total_weighted_revenue_qoq_prev = merged.loc[valid_revenue_qoq, f"weighted_revenue_{prev_qoq_suffix}"].sum()

    if total_revenue_qoq_prev != 0:
        summary["normal_revenue_qoq_growth_pct"] = (
            ((total_revenue_qoq - total_revenue_qoq_prev) / total_revenue_qoq_prev) * 100
        )
    if total_weighted_revenue_qoq_prev != 0:
        summary["weighted_revenue_qoq_growth_pct"] = (
            ((total_weighted_revenue_qoq - total_weighted_revenue_qoq_prev) / total_weighted_revenue_qoq_prev) * 100
        )

    total_profit_qoq = merged.loc[valid_profit_qoq, "net_profit"].sum()
    total_profit_qoq_prev = merged.loc[valid_profit_qoq, qoq_profit_col].sum()
    total_weighted_profit_qoq = merged.loc[valid_profit_qoq, "weighted_profit"].sum()
    total_weighted_profit_qoq_prev = merged.loc[valid_profit_qoq, f"weighted_profit_{prev_qoq_suffix}"].sum()

    if total_profit_qoq_prev != 0:
        summary["normal_profit_qoq_growth_pct"] = (
            ((total_profit_qoq - total_profit_qoq_prev) / total_profit_qoq_prev) * 100
        )
    if total_weighted_profit_qoq_prev != 0:
        summary["weighted_profit_qoq_growth_pct"] = (
            ((total_weighted_profit_qoq - total_weighted_profit_qoq_prev) / total_weighted_profit_qoq_prev) * 100
        )

    if qoq_op_col in merged:
        total_op_qoq = merged.loc[valid_op_qoq, "operating_profit"].sum()
        total_op_qoq_prev = merged.loc[valid_op_qoq, qoq_op_col].sum()
        total_weighted_op_qoq = merged.loc[valid_op_qoq, "weighted_operating_profit"].sum()
        total_weighted_op_qoq_prev = merged.loc[valid_op_qoq, f"weighted_operating_profit_{prev_qoq_suffix}"].sum()
        if total_op_qoq_prev != 0:
            summary["normal_operating_profit_qoq_growth_pct"] = (
                ((total_op_qoq - total_op_qoq_prev) / total_op_qoq_prev) * 100
            )
        if total_weighted_op_qoq_prev != 0:
            summary["weighted_operating_profit_qoq_growth_pct"] = (
                ((total_weighted_op_qoq - total_weighted_op_qoq_prev) / total_weighted_op_qoq_prev) * 100
            )

    return merged, summary


# =========================================================
# GENERATE ANALYSIS
# =========================================================


def generate_analysis(merged_df, summary, index_name, current_quarter, previous_quarter_yoy, previous_quarter_qoq, prev_yoy_suffix, prev_qoq_suffix):
    """
    Generate summary analysis with logs
    """
    logs = []

    # Header
    logs.append(f"\n{'='*80}")
    logs.append(f"{current_quarter} Earnings Analysis - {index_name}")
    logs.append(f"{'='*80}\n")

    # Declared results
    declared_count = len(merged_df[merged_df["revenue"].notna()])
    logs.append(f"Total Declared Companies ({current_quarter}): {declared_count}")

    # Companies with YoY comparison
    with_yoy = len(merged_df[merged_df[f"revenue_{prev_yoy_suffix}"].notna()])
    logs.append(f"Companies with {previous_quarter_yoy} comparison: {with_yoy}\n")

    # Detailed logs
    logs.append(f"\n{'TICKER':<15} {'CUR_REV':>10} {'PY_REV':>10} {'YOY_REV%':>10} {'QOQ_REV':>10} {'QOQ_REV%':>10} {'CUR_OP':>10} {'PY_OP':>10} {'YOY_OP%':>10} {'QOQ_OP':>10} {'QOQ_OP%':>10} {'CUR_PROFIT':>12} {'PY_PROFIT':>12} {'YOY_PROFIT%':>11} {'QOQ_PROFIT':>12} {'QOQ_PROFIT%':>11}")
    logs.append("-" * 180)

    for _, row in merged_df.iterrows():
        ticker = row["ticker"]
        rev_cur = row["revenue"]
        rev_py = row.get(f"revenue_{prev_yoy_suffix}")
        rev_qoq = row.get(f"revenue_{prev_qoq_suffix}")
        rev_yoy = row.get("revenue_yoy_growth")
        profit_cur = row["net_profit"]
        profit_py = row.get(f"net_profit_{prev_yoy_suffix}")
        profit_qoq = row.get(f"net_profit_{prev_qoq_suffix}")
        profit_yoy = row.get("profit_yoy_growth")
        op_cur = row.get("operating_profit")
        op_py = row.get(f"operating_profit_{prev_yoy_suffix}")
        op_qoq = row.get(f"operating_profit_{prev_qoq_suffix}")
        op_yoy = row.get("operating_profit_yoy_growth")
        op_qoq_growth = row.get("operating_profit_qoq_growth")

        rev_yoy_str = f"{rev_yoy:.2f}%" if rev_yoy is not None else "N/A"
        rev_qoq_str = f"{rev_qoq:.2f}%" if rev_qoq is not None else "N/A"
        profit_yoy_str = f"{profit_yoy:.2f}%" if profit_yoy is not None else "N/A"
        profit_qoq_str = f"{profit_qoq:.2f}%" if profit_qoq is not None else "N/A"
        op_yoy_str = f"{op_yoy:.2f}%" if op_yoy is not None else "N/A"
        op_qoq_str = f"{op_qoq_growth:.2f}%" if op_qoq_growth is not None else "N/A"

        log_line = (
            f"{ticker:<15} {rev_cur:>10.0f} {rev_py if rev_py else 0:>10.0f} {rev_yoy_str:>10} "
            f"{rev_qoq if rev_qoq else 0:>10.0f} {rev_qoq_str:>10} {op_cur if op_cur else 0:>10.0f} {op_py if op_py else 0:>10.0f} {op_yoy_str:>10} "
            f"{op_qoq if op_qoq else 0:>10.0f} {op_qoq_str:>10} {profit_cur:>12.0f} {profit_py if profit_py else 0:>12.0f} {profit_yoy_str:>11} "
            f"{profit_qoq if profit_qoq else 0:>12.0f} {profit_qoq_str:>11}"
        )
        logs.append(log_line)

    # Summary statistics
    logs.append("\n" + "=" * 100)
    logs.append(f"Summary Statistics - YoY ({current_quarter} vs {previous_quarter_yoy}):")
    logs.append("=" * 100)

    avg_rev_yoy = merged_df[merged_df["revenue_yoy_growth"].notna()]["revenue_yoy_growth"].mean()
    avg_profit_yoy = merged_df[merged_df["profit_yoy_growth"].notna()]["profit_yoy_growth"].mean()
    avg_op_yoy = merged_df[merged_df["operating_profit_yoy_growth"].notna()]["operating_profit_yoy_growth"].mean()
    median_rev_yoy = merged_df[merged_df["revenue_yoy_growth"].notna()]["revenue_yoy_growth"].median()
    median_profit_yoy = merged_df[merged_df["profit_yoy_growth"].notna()]["profit_yoy_growth"].median()
    median_op_yoy = merged_df[merged_df["operating_profit_yoy_growth"].notna()]["operating_profit_yoy_growth"].median()

    logs.append(f"\nRevenue YoY Growth:")
    logs.append(f"  Average: {avg_rev_yoy:.2f}%")
    logs.append(f"  Median:  {median_rev_yoy:.2f}%")

    logs.append(f"\nOperating Profit YoY Growth:")
    logs.append(f"  Average: {avg_op_yoy:.2f}%")
    logs.append(f"  Median:  {median_op_yoy:.2f}%")

    logs.append(f"\nProfit YoY Growth:")
    logs.append(f"  Average: {avg_profit_yoy:.2f}%")
    logs.append(f"  Median:  {median_profit_yoy:.2f}%")

    logs.append("\n" + "=" * 100)
    logs.append(f"Summary Statistics - QoQ ({current_quarter} vs {previous_quarter_qoq}):")
    logs.append("=" * 100)

    avg_rev_qoq = merged_df[merged_df["revenue_qoq_growth"].notna()]["revenue_qoq_growth"].mean()
    avg_profit_qoq = merged_df[merged_df["profit_qoq_growth"].notna()]["profit_qoq_growth"].mean()
    avg_op_qoq = merged_df[merged_df["operating_profit_qoq_growth"].notna()]["operating_profit_qoq_growth"].mean()
    median_rev_qoq = merged_df[merged_df["revenue_qoq_growth"].notna()]["revenue_qoq_growth"].median()
    median_profit_qoq = merged_df[merged_df["profit_qoq_growth"].notna()]["profit_qoq_growth"].median()
    median_op_qoq = merged_df[merged_df["operating_profit_qoq_growth"].notna()]["operating_profit_qoq_growth"].median()

    logs.append(f"\nRevenue QoQ Growth:")
    logs.append(f"  Average: {avg_rev_qoq:.2f}%")
    logs.append(f"  Median:  {median_rev_qoq:.2f}%")

    logs.append(f"\nOperating Profit QoQ Growth:")
    logs.append(f"  Average: {avg_op_qoq:.2f}%")
    logs.append(f"  Median:  {median_op_qoq:.2f}%")

    logs.append(f"\nProfit QoQ Growth:")
    logs.append(f"  Average: {avg_profit_qoq:.2f}%")
    logs.append(f"  Median:  {median_profit_qoq:.2f}%")

    logs.append("\n" + "=" * 100)
    logs.append("Index-Level Summary:")
    logs.append("=" * 100)
    logs.append(f"Declared Index Weight Represented: {summary['declared_weight_pct']:.2f}%")

    def fmt_pct(value):
        return f"{value:.2f}%" if value is not None else "N/A"

    logs.append(f"\nNormal Revenue YoY Growth (index aggregate): {fmt_pct(summary['normal_revenue_yoy_growth_pct'])}")
    logs.append(f"Weighted Revenue YoY Growth: {fmt_pct(summary['weighted_revenue_yoy_growth_pct'])}")
    logs.append(f"Normal Operating Profit YoY Growth (index aggregate): {fmt_pct(summary['normal_operating_profit_yoy_growth_pct'])}")
    logs.append(f"Weighted Operating Profit YoY Growth: {fmt_pct(summary['weighted_operating_profit_yoy_growth_pct'])}")
    logs.append(f"Normal Profit YoY Growth (index aggregate): {fmt_pct(summary['normal_profit_yoy_growth_pct'])}")
    logs.append(f"Weighted Profit YoY Growth: {fmt_pct(summary['weighted_profit_yoy_growth_pct'])}")

    logs.append(f"\nNormal Revenue QoQ Growth (index aggregate): {fmt_pct(summary['normal_revenue_qoq_growth_pct'])}")
    logs.append(f"Weighted Revenue QoQ Growth: {fmt_pct(summary['weighted_revenue_qoq_growth_pct'])}")
    logs.append(f"Normal Operating Profit QoQ Growth (index aggregate): {fmt_pct(summary['normal_operating_profit_qoq_growth_pct'])}")
    logs.append(f"Weighted Operating Profit QoQ Growth: {fmt_pct(summary['weighted_operating_profit_qoq_growth_pct'])}")
    logs.append(f"Normal Profit QoQ Growth (index aggregate): {fmt_pct(summary['normal_profit_qoq_growth_pct'])}")
    logs.append(f"Weighted Profit QoQ Growth: {fmt_pct(summary['weighted_profit_qoq_growth_pct'])}")

    logs.append(f"\nAnalysis generated at: {datetime.now().isoformat()}")
    logs.append("=" * 80)

    return logs


# =========================================================
# SAVE RESULTS
# =========================================================


def save_results(merged_df, logs, quarter_label):
    """
    Save combined results to a CSV and logs file using the quarter_label in filenames.
    """
    # output_dir = BASE_DIR / "earnings"
    # output_dir.mkdir(parents=True, exist_ok=True)
    safe_q = quarter_label.lower().replace(" ", "_")
    output_csv = DATA_DIR / f"all_indices_{safe_q}_analysis.csv"
    merged_df.to_csv(output_csv, index=False)
    print(f"[INFO] Combined results saved to: {output_csv}")

    output_txt = DATA_DIR / f"all_indices_{safe_q}_analysis_logs.txt"
    with open(output_txt, "w") as f:
        f.write("\n".join(logs))
    print(f"[INFO] Combined logs saved to: {output_txt}")


def save_summary(summary_df):
    """
    Save the India Inc earnings summary for all indices.
    """
    output_csv = DATA_DIR / "india_inc_earnings_summary.csv"
    existing_df = None
    if output_csv.exists():
        try:
            existing_df = pd.read_csv(output_csv)
        except Exception:
            existing_df = None

    if existing_df is not None and not existing_df.empty:
        combined = pd.concat([existing_df, summary_df], ignore_index=True)
        combined["quarter_sort_key"] = combined["quarter_label"].apply(quarter_sort_key)
        combined = combined.sort_values(by=["index_name", "quarter_sort_key"], ascending=[True, False])
        combined = combined.drop_duplicates(subset=["index_name", "quarter_label"], keep="first")
        combined = combined.drop(columns=["quarter_sort_key"])
        summary_df = combined
    summary_df.to_csv(output_csv, index=False)
    print(f"[INFO] India Inc earnings summary saved to: {output_csv}")


def add_quarter_metadata(summary_row, quarter_label):
    parsed = parse_quarter_label(quarter_label)
    summary_row["quarter_label"] = quarter_label
    if parsed is None:
        summary_row["quarter"] = None
        summary_row["financial_year"] = None
        return summary_row

    quarter, year = parsed
    summary_row["quarter"] = f"Q{quarter}"
    summary_row["financial_year"] = f"FY{year % 100:02d}"
    return summary_row


# =========================================================
# MAIN
# =========================================================


def main():
    # Load data once
    df = load_earnings_data()
    current_quarter = get_latest_quarter_label(df)
    if current_quarter is None:
        raise ValueError("Unable to detect current quarter from earnings data.")

    print("\n" + "=" * 80)
    print(f"Local Earnings Analysis - Multi-index {current_quarter}")
    print("=" * 80 + "\n")

    previous_quarter_yoy, previous_quarter_qoq = get_previous_quarters(current_quarter)
    prev_yoy_suffix = quarter_label_to_suffix(previous_quarter_yoy)
    prev_qoq_suffix = quarter_label_to_suffix(previous_quarter_qoq)
    prev_yoy_data = get_previous_quarter_data(df, previous_quarter_yoy, prev_yoy_suffix)
    prev_qoq_data = get_previous_quarter_data(df, previous_quarter_qoq, prev_qoq_suffix)

    combined_results = []
    combined_logs = []
    combined_summaries = []

    for index_name in INDEX_NAMES:
        print("\n" + "-" * 80)
        print(f"Analyzing {index_name}")
        print("-" * 80 + "\n")

        index_constituents = fetch_index_constituents(index_name)
        declared_q4_fy26 = get_declared_current_quarter(df, index_constituents, index_name, current_quarter)
        merged_df, summary = calculate_growth_metrics(declared_q4_fy26, prev_yoy_data, prev_qoq_data, prev_yoy_suffix, prev_qoq_suffix)

        merged_df["index_name"] = index_name
        combined_results.append(merged_df)

        summary_row = summary.copy()
        summary_row["index_name"] = index_name
        summary_row = add_quarter_metadata(summary_row, current_quarter)
        combined_summaries.append(summary_row)

        logs = generate_analysis(
            merged_df,
            summary,
            index_name,
            current_quarter,
            previous_quarter_yoy,
            previous_quarter_qoq,
            prev_yoy_suffix,
            prev_qoq_suffix,
        )
        combined_logs.extend(logs)

    final_df = pd.concat(combined_results, ignore_index=True)
    save_results(final_df, combined_logs, current_quarter)

    summary_df = pd.DataFrame(combined_summaries)
    save_summary(summary_df)

    print("\n[INFO] Multi-index analysis complete!")


# =========================================================
# ENTRY
# =========================================================

if __name__ == "__main__":
    main()
