from yahoo_provider import YahooDataProvider
from data_loader import DataLoader
from nifty500_universe import Nifty500Universe

universe = Nifty500Universe()
symbols = universe.get_symbols()

provider = YahooDataProvider()
loader = DataLoader(provider)

loader.update_universe(symbols)

print("Data update complete.")
