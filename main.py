from yahoo_provider import YahooDataProvider
from data_loader import DataLoader
from nifty200_universe import Nifty200Universe


def main():

    print("Fetching Nifty 200 symbols...")
    universe = Nifty200Universe()
    symbols = universe.get_symbols()

    print(f"Total symbols: {len(symbols)}")

    provider = YahooDataProvider()
    loader = DataLoader(provider)

    print("Updating data...")
    loader.update_universe(symbols)

    print("Done.")


if __name__ == "__main__":
    main()
