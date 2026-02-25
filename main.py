from yahoo_provider import YahooDataProvider
from data_loader import DataLoader
from nifty500_universe import Nifty500Universe


def main():

    print("Fetching Nifty 500 symbols...")
    universe = Nifty500Universe()
    symbols = universe.get_symbols()

    print(f"Total symbols: {len(symbols)}")

    provider = YahooDataProvider()
    loader = DataLoader(provider)

    print("Updating data...")
    loader.update_universe(symbols)

    print("Done.")


if __name__ == "__main__":
    main()
