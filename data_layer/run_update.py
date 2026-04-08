from yahoo_provider import YahooDataProvider
from data_loader import DataLoader
from all_nse_universe import AllNSEUniverse

if __name__ == "__main__":

    # symbols = AllNSEUniverse().get_symbols()
    symbols=["SBIN.NS"]
    loader = DataLoader(provider=YahooDataProvider(), data_dir="data/test2")
    loader.update_universe(symbols)
    print("data update complete...........")