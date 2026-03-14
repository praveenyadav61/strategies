# from yahoo_provider import YahooDataProvider
# from data_layer.data_loader import DataLoader
# from nifty500_universe import Nifty500Universe
from engine.backtest_engine import BacktestEngine
from data_layer.data_engine import DataEngine
from engine.portfolio import Portfolio

def main():

    data_engine = DataEngine()

    portfolio = Portfolio(1000000)

    engine = BacktestEngine(data_engine, portfolio)

    equity = engine.run("RELIANCE", momentum_strategy)

    # print("Fetching Nifty 500 symbols...")
    # universe = Nifty500Universe()
    # symbols = universe.get_symbols()

    # print(f"Total symbols: {len(symbols)}")

    # provider = YahooDataProvider()
    # loader = DataLoader(provider)

    # print("Updating data...")
    # loader.update_universe(symbols)

    # print("Done.")


if __name__ == "__main__":
    main()
