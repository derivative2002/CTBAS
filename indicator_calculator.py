import numpy as np


class IndicatorCalculator:
    def __init__(self, ma_periods, trend_ma_period, atr_period):
        self.ma_periods = ma_periods
        self.trend_ma_period = trend_ma_period
        self.atr_period = atr_period

    def calculate_ma(self, close_prices):
        ma_values = []
        for period in self.ma_periods:
            ma_values.append(np.mean(close_prices[:period]))
        return ma_values

    def calculate_trend_ma(self, close_prices):
        return np.mean(close_prices[:self.trend_ma_period])

    def calculate_atr(self, high_prices, low_prices, close_prices):
        tr = np.zeros(len(high_prices))
        tr[0] = high_prices[0] - low_prices[0]
        for i in range(1, len(high_prices)):
            tr[i] = max(high_prices[i] - low_prices[i],
                        abs(high_prices[i] - close_prices[i - 1]),
                        abs(low_prices[i] - close_prices[i - 1]))

        atr = np.zeros(len(tr))
        atr[0] = tr[0]
        for i in range(1, len(tr)):
            atr[i] = (atr[i - 1] * (self.atr_period - 1) + tr[i]) / self.atr_period

        return atr[-1]
