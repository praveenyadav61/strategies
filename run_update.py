from yahoo_provider import YahooDataProvider
from data_loader import DataLoader
from nifty200_universe import Nifty200Universe

universe = Nifty200Universe()
symbols = universe.get_symbols()

provider = YahooDataProvider()
loader = DataLoader(provider)

loader.update_universe(symbols)

print("Data update complete.")
