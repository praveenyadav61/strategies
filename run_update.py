from yahoo_provider import YahooDataProvider
from data_layer.data_loader import DataLoader
from nifty500_universe import Nifty500Universe
from all_nse_universe import AllNSEUniverse

# universe = Nifty500Universe()
universe = AllNSEUniverse()
symbols = universe.get_symbols()
# symbols = symbols[:1]  # Limit to first 10 for testing
# print(symbols)
provider = YahooDataProvider()
loader = DataLoader(provider)

loader.update_universe(symbols)

print("Data update complete.")
