import requests

url = 'https://api.upstox.com/v2/fundamentals/INE002A01018/share-holdings'
headers = {
    'Accept': 'application/json',
    'Authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIzTkNYRUsiLCJqdGkiOiI2YTVkYTNjZTJiOWNhODI2YTkwZDhjMzgiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlzRXh0ZW5kZWQiOnRydWUsImlhdCI6MTc4NDUyMTY3OCwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxODE2MTIwODAwfQ.XepG37qYtnz-dePmSO1s0UeUzK-aMJbzuGeulI6thbg'
}

response = requests.get(url, headers=headers)
print(response.json())



# from pathlib import Path
# import pandas as pd

# # Path to your parquet file
# parquet_file = Path("C:\\Users\\Praveen Yadav\\OneDrive\\Projects\\strategies\\data\\static\\weightage.parquet")

# # Read parquet
# df = pd.read_parquet(parquet_file)

# # Create CSV path in the same folder with the same filename
# csv_file = parquet_file.with_suffix(".csv")

# # Save as CSV
# df.to_csv(csv_file, index=False)

# print(f"CSV saved to: {csv_file}")