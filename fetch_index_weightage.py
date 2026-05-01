"""
Comprehensive Index Weightage Fetcher (Optimized)
==================================================
Fetches real-time constituents and weightages for ALL Indian NSE Indices.
Uses nsetools library to extract data directly from NSE.

Optimizations:
- Parallel fetching using ThreadPoolExecutor
- Vectorized DataFrame operations
- Efficient memory management
- Progress tracking with ETA

Categories:
1. Broad Market Indices
2. Sector Indices  
3. Factor-Based Indices (Quality, Momentum, Value, Low Volatility)
4. Strategy Indices
5. Thematic Indices
    'Broad Market': [
        'NIFTY 50', 'NIFTY NEXT 50', 'NIFTY 100', 'NIFTY 200', 'NIFTY 500',
        'NIFTY MID SELECT', 'NIFTY MIDCAP 50', 'NIFTY MIDCAP 100', 'NIFTY MIDCAP 150',
        'NIFTY SMLCAP 50', 'NIFTY SMLCAP 100', 'NIFTY SMLCAP 250', 'NIFTY MIDSML 400',
        'NIFTY500 MULTICAP', 'NIFTY LARGEMID250', 'NIFTY TOTAL MKT', 'NIFTY MICROCAP250',
    ],
"""

import os
import pandas as pd
from nsetools import Nse
from tqdm import tqdm
import warnings
import time
import argparse
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

warnings.filterwarnings('ignore')

# Thread-safe counter for progress tracking
counter_lock = threading.Lock()
completed_count = 0
failed_count = 0

OUTPUT_COLUMNS = ['index', 'symbol', 'average', 'category']
DEDUP_COLUMNS = ['index', 'symbol']
logger = logging.getLogger(__name__)

# ============================================================================
# INDEX CATEGORIES - Grouped by type for organized fetching
# ============================================================================

INDEX_CATEGORIES = {
    'Broad Market': [
        'NIFTY 50', 'NIFTY NEXT 50', 'NIFTY 200', 'NIFTY 500',
        'NIFTY MID SELECT', 'NIFTY MIDCAP 100', 'NIFTY MIDCAP 150'
        , 'NIFTY SMLCAP 100', 'NIFTY SMLCAP 250', 'NIFTY TOTAL MKT', 'NIFTY MICROCAP250',
    ],
    
    'Sector Indices': [
        'NIFTY AUTO', 'NIFTY BANK', 'NIFTY FIN SERVICE', 'NIFTY FMCG', 'NIFTY IT',
        'NIFTY MEDIA', 'NIFTY METAL', 'NIFTY PHARMA', 'NIFTY PSU BANK', 'NIFTY PVT BANK',
        'NIFTY REALTY', 'NIFTY HEALTHCARE', 'NIFTY CONSR DURBL', 'NIFTY OIL AND GAS',
        'NIFTY ENERGY', 'NIFTY CHEMICALS', 'NIFTY CONSUMPTION', 'NIFTY INFRA', 'NIFTY MNC',
        'NIFTY PSE', 'NIFTY SERV SECTOR', 'NIFTY CAPITAL MKT',
    ],
    
    'Factor-Based (Quality)': [
        'NIFTY100 QUALTY30', 'NIFTY200 QUALTY30', 'NIFTY MS FIN SERV',
        'NIFTY MS IT TELCM', 'NIFTY500 HEALTH', 'NIFTY MS IND CONS',
    ],
    
    'Factor-Based (Momentum)': [
        'NIFTY200MOMENTM30', 'NIFTYM150MOMNTM50', 'NIFTY500MOMENTM50',
    ],
    
    # 'Factor-Based (Value)': [
    #     'NIFTY50 VALUE 20', 'NIFTY200 VALUE 30', 'NIFTY500 VALUE 50',
    # ],
    
    # 'Factor-Based (Low Volatility)': [
    #     'NIFTY100 LOWVOL30', 'NIFTY ALPHALOWVOL', 'NIFTY LOW VOL 50',
    #     'NIFTY QLTY LV 30', 'NIFTY500 LOWVOL50',
    # ],
    
    # 'Factor-Based (Alpha)': [
    #     'NIFTY ALPHA 50', 'NIFTY200 ALPHA 30', 'NIFTY100 ALPHA 30',
    # ],
    
    # 'Factor-Based (Multi-Factor)': [
    #     'NIFTY MS400 MQ 100', 'NIFTYSML250MQ 100', 'NIFTY MULTI MQ 50',
    #     'NIFTY500 MQVLV50', 'NIFTY TMMQ 50',
    # ],
    
    # 'Strategy (Equal Weight)': [
    #     'NIFTY50 EQL WGT', 'NIFTY100 EQL WGT',
    # ],
    
    # 'Strategy (Others)': [
    #     'NIFTY DIV OPPS 50', 'NIFTY50 DIV POINT', 'NIFTY TOP 10 EW',
    #     'NIFTY TOP 15 EW', 'NIFTY TOP 20 EW', 'NIFTY500 EW', 'NIFTY500 FLEXICAP',
    # ],
    
    'Thematic': [
        'NIFTY IND DIGITAL', 'NIFTY INDIA MFG', 'NIFTY IND DEFENCE', 'NIFTY IND TOURISM',
        'NIFTY EV', 'NIFTY NEW CONSUMP', 'NIFTY MOBILITY', 'NIFTY INTERNET',
        'NIFTY TRANS LOGIS', 'NIFTY RAILWAYSPSU', 'NIFTY COREHOUSING', 'NIFTY HOUSING',
        'NIFTY RURAL', 'NIFTY NONCYC CONS',
    ],
    
    # 'ESG & Sustainability': [
    #     'NIFTY100ESGSECLDR', 'NIFTY100 ESG', 'NIFTY100 ENH ESG',
    # ],
}


def build_index_category_map() -> dict:
    """Return index-to-category mapping and fail fast if config has repeats."""
    duplicate_indices = [
        idx
        for indices in INDEX_CATEGORIES.values()
        for idx in indices
        if sum(idx in values for values in INDEX_CATEGORIES.values()) > 1
    ]
    if duplicate_indices:
        duplicates = ", ".join(sorted(set(duplicate_indices)))
        raise ValueError(f"Duplicate index definitions found: {duplicates}")

    return {
        idx: category
        for category, indices in INDEX_CATEGORIES.items()
        for idx in indices
    }


def empty_weightage_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def normalize_and_deduplicate(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Normalize schema and remove duplicate constituents for each index."""
    if df.empty:
        return empty_weightage_frame(), 0

    normalized = df.copy()
    normalized['index'] = normalized['index'].astype(str).str.strip().str.upper()
    normalized['symbol'] = normalized['symbol'].astype(str).str.strip().str.upper()
    normalized['average'] = pd.to_numeric(normalized['average'], errors='coerce').fillna(0).round(2)
    normalized['category'] = normalized['category'].astype(str).str.strip()
    normalized = normalized[normalized['index'].ne('') & normalized['symbol'].ne('')]

    before = len(normalized)
    normalized = (
        normalized
        .sort_values(['index', 'symbol', 'average'], ascending=[True, True, False])
        .drop_duplicates(subset=DEDUP_COLUMNS, keep='first')
        .sort_values(['index', 'average', 'symbol'], ascending=[True, False, True])
        .reset_index(drop=True)
    )
    return normalized[OUTPUT_COLUMNS], before - len(normalized)


def fetch_single_index(index_name: str, category: str, nse_client: Nse) -> tuple:
    """
    Fetch weightage data for a single index (thread-safe).
    Returns tuple of (index_name, DataFrame or None, error_message)
    """
    global counter_lock, completed_count, failed_count
    
    try:
        stock_quotes = nse_client.get_stock_quote_in_index(index_name)
        
        if not stock_quotes or len(stock_quotes) == 0:
            with counter_lock:
                failed_count += 1
            return (index_name, None, "No data returned")
        
        # Vectorized extraction using list comprehension
        stocks_data = [
            {'symbol': str(q.get('symbol', '')).strip().upper(), 'ffmc': q.get('ffmc', 0)}
            for q in stock_quotes
            if (
                q.get('priority', 0) == 0
                and str(q.get('symbol', '')).strip().upper() != index_name.upper()
                and q.get('ffmc', 0) > 0
            )
        ]
        
        if not stocks_data:
            with counter_lock:
                failed_count += 1
            return (index_name, None, "No valid stocks")
        
        # Calculate total FFMC
        total_ffmc = sum(s['ffmc'] for s in stocks_data)
        
        # Vectorized weightage calculation
        data_rows = [
            {
                'index': index_name,
                'symbol': stock['symbol'],
                'average': round((stock['ffmc'] / total_ffmc) * 100, 2) if total_ffmc > 0 else 0,
                'category': category,
            }
            for stock in stocks_data
        ]
        
        df, _ = normalize_and_deduplicate(pd.DataFrame(data_rows))
        
        with counter_lock:
            completed_count += 1
        
        return (index_name, df, None)
        
    except Exception as e:
        with counter_lock:
            failed_count += 1
        return (index_name, None, str(e))


def fetch_all_indices_parallel(max_workers: int = 10, show_progress: bool = True) -> pd.DataFrame:
    """
    Fetch all indices in parallel using ThreadPoolExecutor.
    """
    global counter_lock, completed_count, failed_count
    
    # Reset counters
    counter_lock = threading.Lock()
    completed_count = 0
    failed_count = 0
    
    try:
        nse_client = Nse()
    except Exception as e:
        logger.error("Failed to initialize NSE client: %s", e)
        return empty_weightage_frame()
    
    # Flatten all indices from categories
    index_to_category = build_index_category_map()
    all_indices = list(index_to_category.items())
    
    total_indices = len(all_indices)
    all_data = []
    failed_indices = []
    
    logger.info(
        "Fetching weightages for %s indices across %s categories with %s workers.",
        total_indices,
        len(INDEX_CATEGORIES),
        max_workers,
    )
    
    start_time = time.time()
    
    # Process in parallel with ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_index = {
            executor.submit(fetch_single_index, idx, cat, nse_client): (idx, cat)
            for idx, cat in all_indices
        }
        
        # Process results with progress bar
        with tqdm(total=total_indices, desc="Fetching", unit="idx", disable=not show_progress) as pbar:
            for future in as_completed(future_to_index):
                index_name, df, error = future.result()
                
                if df is not None and not df.empty:
                    all_data.append(df)
                else:
                    failed_indices.append((index_name, error))
                
                pbar.update(1)
    
    elapsed_time = time.time() - start_time
    
    if not all_data:
        logger.warning("No data could be fetched from any index.")
        return empty_weightage_frame()
    
    # Combine all DataFrames efficiently
    combined_df = pd.concat(all_data, ignore_index=True)
    combined_df, duplicate_count = normalize_and_deduplicate(combined_df)
    
    # Print summary
    logger.info(
        "Fetched %s records (%s indices, %s symbols) in %.1fs.",
        len(combined_df),
        combined_df['index'].nunique(),
        combined_df['symbol'].nunique(),
        elapsed_time,
    )
    if duplicate_count:
        logger.info("Removed %s duplicate rows on %s.", duplicate_count, DEDUP_COLUMNS)
    
    if failed_indices:
        preview = ", ".join(f"{idx} ({err})" for idx, err in failed_indices[:5])
        logger.warning("Failed indices: %s of %s. First failures: %s", len(failed_indices), total_indices, preview)
    
    return combined_df


def save_to_parquet(df: pd.DataFrame, output_path: str = "data/static/weightage.parquet"):
    """Save DataFrame to parquet file."""
    df, duplicate_count = normalize_and_deduplicate(df)
    duplicate_rows = df.duplicated(subset=DEDUP_COLUMNS).sum()
    if duplicate_rows:
        raise ValueError(f"Duplicate rows remain on {DEDUP_COLUMNS}: {duplicate_rows}")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_parquet(output_path, index=False)
    logger.info("Saved %s records to %s.", len(df), output_path)
    if duplicate_count:
        logger.info("Removed %s duplicate rows before saving.", duplicate_count)


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch NSE index constituent weightages.")
    parser.add_argument("--output", default="data/static/weightage.parquet", help="Output parquet path.")
    parser.add_argument("--max-workers", type=int, default=10, help="Number of parallel fetch workers.")
    parser.add_argument("--quiet", action="store_true", help="Only print warnings and errors.")
    parser.add_argument("--verbose", action="store_true", help="Print debug details and summaries.")
    parser.add_argument("--no-progress", action="store_true", help="Disable tqdm progress bar.")
    return parser.parse_args()


def configure_logging(verbose: bool = False, quiet: bool = False):
    level = logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def main():
    """Main execution function."""
    args = parse_args()
    configure_logging(verbose=args.verbose, quiet=args.quiet)

    try:
        # Fetch all index weightages (parallel)
        df = fetch_all_indices_parallel(max_workers=args.max_workers, show_progress=not args.no_progress)
        
        if df.empty:
            logger.warning("No data fetched. Please check your internet connection.")
            return
        
        if args.verbose:
            category_summary = df.groupby('category').agg({
                'symbol': 'count',
                'index': 'nunique'
            }).rename(columns={'symbol': 'records', 'index': 'indices'})
            logger.debug("Sample data:\n%s", df.head(15).to_string(index=False))
            logger.debug("Records by category:\n%s", category_summary.to_string())
        
        # Save to parquet
        save_to_parquet(df, args.output)
        
        logger.info("Index weightage fetch completed at %s.", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        raise


if __name__ == "__main__":
    main()
