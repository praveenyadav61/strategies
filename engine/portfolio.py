class Portfolio:

    def __init__(self, initial_cash=1000000):

        self.cash = initial_cash
        self.positions = {}
        self.equity_curve = []

    def buy(self, symbol, price, quantity):

        cost = price * quantity

        if self.cash >= cost:

            self.cash -= cost

            self.positions[symbol] = self.positions.get(symbol, 0) + quantity

    def sell(self, symbol, price, quantity):

        if symbol in self.positions:

            self.cash += price * quantity

            self.positions[symbol] -= quantity

            if self.positions[symbol] == 0:
                del self.positions[symbol]

    def total_value(self, prices):

        value = self.cash

        for symbol, qty in self.positions.items():

            value += prices[symbol] * qty

        return value