from data_layer.data_engine import DataEngine
from engine.portfolio import Portfolio
from engine.backtest_engine import BacktestEngine
from engine.metrics import sharpe_ratio, max_drawdown
from strategies import momentum


def main():

    symbol = "RELIANCE.NS"

    # Load data
    data_engine = DataEngine()

    data = data_engine.get_symbol(symbol)

    print("Loaded data:", len(data))

    # Initialize portfolio
    portfolio = Portfolio(initial_cash=1_000_000)

    # Initialize backtest engine
    engine = BacktestEngine(data_engine, portfolio)

    # Run backtest
    equity_curve = engine.run(symbol, momentum)

    # Metrics
    sharpe = sharpe_ratio(equity_curve)
    drawdown = max_drawdown(equity_curve)

    print("Backtest Results")
    print("----------------")
    print("Final Equity:", equity_curve[-1])
    print("Sharpe:", sharpe)
    print("Max Drawdown:", drawdown)


if __name__ == "__main__":
    main()