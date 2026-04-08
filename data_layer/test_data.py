###to test which doesn't have ;last working day data
# import os
# import pandas as pd

# DATA_DIR = "data/daily"
# TARGET_DATE = pd.Timestamp("2026-04-02")

# missing_files = []

# for file in os.listdir(DATA_DIR):
#     if not file.endswith(".parquet"):
#         continue

#     path = os.path.join(DATA_DIR, file)

#     try:
#         df = pd.read_parquet(path)

#         if df.empty or TARGET_DATE not in df.index:
#             missing_files.append(file)

#     except Exception as e:
#         print(f"Error reading {file}: {e}")
#         missing_files.append(file)

# # Output
# print(f"\nFiles missing {TARGET_DATE.date()}: {len(missing_files)}\n")

# for f in missing_files[:20]:  # show first 20
#     print(f)

# # Optional: save full list
# with open("missing_2026_04_02.txt", "w") as f:
#     for file in missing_files:
#         f.write(file + "\n")

#####################################################


import os
import pandas as pd

DATA_DIR = "data/daily"

files = [f for f in os.listdir(DATA_DIR) if f.endswith("SBIN.NS.parquet")][:2]

for file in files:
    path = os.path.join(DATA_DIR, file)

    try:
        df = pd.read_parquet(path)

        print(f"\n===== {file} =====")
        print(df.tail(10))

    except Exception as e:
        print(f"Error reading {file}: {e}")


# import yfinance as yf
# import pandas as pd

# # Symbol
# symbol = "SBIN.NS"

# # Fetch data
# df = yf.download(symbol, start="2026-03-01",end="2026-04-02", interval="1d")

# # Show raw
# print("Raw data:")
# print(df.tail())
# # 🔥 FIX: flatten MultiIndex ALWAYS
# if isinstance(df.columns, pd.MultiIndex):
#     df.columns = df.columns.get_level_values(0)

# print("\nAfter flattening MultiIndex:")
# print(df.tail())
# # Keep only required columns
# # df = df[["Open", "High", "Low", "Close", "Volume"]]
# # required_cols = ["Open", "High", "Low", "Close", "Volume"]

# # df = df.loc[:, df.columns.intersection(required_cols)]
# # df = df[required_cols]

# # Remove NaNs (important)
# df = df.dropna(subset=["Close"])

# # Clean (optional but recommended)
# if not df.empty:
#     df = df[["Open", "High", "Low", "Close", "Volume"]]
#     df = df.dropna(subset=["Close"])  # remove bad rows
#     df.index.name = "Date"

#     print("\nCleaned data:")
#     print(df.tail())
# else:
#     print("❌ No data fetched")