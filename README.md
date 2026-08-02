
Base Lifecycle documentation
----------------------------

- `base_lifecycle_flow.md`: end-to-end scan, replay, snapshot, and tracking overview.
- `base_lifecycle_pivot_breakout.md`: authoritative pivot construction, breakout confirmation, freezing, retest, and failure rules.

Use the focused pivot/breakout document as the reference for future changes to
`Streamlit/base_lifecycle_scanner.py`.

MarketDataEngine
-----------------------

Purpose: Unified data provider that returns daily (local Parquet) or intraday (on‑demand via yfinance) market data as a pandas DataFrame.

Initialization: `MarketDataEngine(daily_data_dir='data/daily', intraday_store_dir=None, cache_in_memory=True)`

Primary method: `get_data(symbol, start=None, end=None, interval='1d', last_n=None, persist=False, provider_kwargs=None)`
- `symbol`: ticker string (e.g. `RELIANCE.NS`)
- `start`, `end`: datetimes or parseable strings (intraday accepts full timestamp)
- `interval`: daily -> `'1d'` (or `'daily'`), intraday -> `'1m','2m','5m','15m','30m','60m','90m','120m'`
- `last_n`: integer for last N rows (daily loader)
- `persist`: if True, saves fetched data to disk (`intraday_store_dir` for intraday, `daily_data_dir` for direct daily fetch)
- `provider_kwargs`: provider-specific kwargs forwarded to yfinance (e.g. `period='1d'`)

Return: `pandas.DataFrame` with a datetime index and columns including `Open, High, Low, Close, Volume`. Intraday index name = `Time`.

Behavior:
- Daily intervals are served from local Parquet files in `daily_data_dir` (use `list_daily_symbols()` to inspect available files).
- Intraday intervals are fetched on-demand (no storage by default). If no data is returned, the engine retries with `Ticker.history()` and raises a clear error if still empty.
- Caching: in-memory cache enabled by `cache_in_memory=True`.

Quick examples:
- Daily from local storage:
  - `engine = MarketDataEngine(daily_data_dir='data/daily')`
  - `df = engine.get_data('RELIANCE.NS', start='2026-05-01', end='2026-05-31', interval='1d')`
- Daily direct fetch from provider:
  - `df = engine.get_daily_direct('RELIANCE.NS', start='2026-05-01', end='2026-05-31')`
- Intraday direct fetch:
  - `df = engine.get_intraday_direct('RELIANCE.NS', start='2026-06-03 09:15:00', end='2026-06-03 15:30:00', interval='1m')`
- Persist direct daily results locally:
  - `df = engine.get_daily_direct('RELIANCE.NS', start='2026-05-01', end='2026-05-31', persist=True)`
- Persist intraday results locally:
  - `engine = MarketDataEngine(daily_data_dir='data/daily', intraday_store_dir='data/intraday')`
  - `df = engine.get_intraday_direct('RELIANCE.NS', start='2026-06-03 09:15:00', end='2026-06-03 15:30:00', interval='1m', persist=True)`

