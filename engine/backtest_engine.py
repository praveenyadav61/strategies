class BacktestEngine:

    def __init__(self, data_engine, portfolio):

        self.data_engine = data_engine
        self.portfolio = portfolio

    def run(self, symbol, strategy):

        data = self.data_engine.get_symbol(symbol)

        signals = strategy.generate_signals(data)
        print("signals :\n",  signals)

        for i in range(len(data) - 1):

            date = data.index[i]

            next_open = data["Open"].iloc[i + 1]

            signal = signals.iloc[i]

            if signal == "BUY":

                self.portfolio.buy(symbol, next_open, 10)

            elif signal == "SELL":

                self.portfolio.sell(symbol, next_open, 10)

            price = data["Close"].iloc[i]

            total_value = self.portfolio.total_value({symbol: price})

            self.portfolio.equity_curve.append(total_value)

        return self.portfolio.equity_curve