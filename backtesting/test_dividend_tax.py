import unittest
from unittest.mock import patch
import pandas as pd
import config
from dividend_tax import holding_period_rate
from portfolio import Portfolio


class TestHoldingPeriodRate(unittest.TestCase):
    entry = pd.Timestamp('2026-05-06')

    def test_short(self):
        self.assertEqual(holding_period_rate(self.entry, '2026-06-05'), 0.20)
        self.assertEqual(holding_period_rate(self.entry, '2026-06-06'), 0.20)

    def test_medium(self):
        self.assertEqual(holding_period_rate(self.entry, '2026-06-07'), 0.10)
        self.assertEqual(holding_period_rate(self.entry, '2027-05-05'), 0.10)
        self.assertEqual(holding_period_rate(self.entry, '2027-05-06'), 0.10)

    def test_long(self):
        self.assertEqual(holding_period_rate(self.entry, '2027-05-07'), 0.0)


class TestPortfolioTax(unittest.TestCase):
    def test_sell_tax_is_deducted(self):
        p = Portfolio(100000)
        p.buy_shares('600000', 100, 10, trade_date='2026-05-06')
        with patch('portfolio.tax_for_lot', return_value=10.0):
            trade = p.sell_shares('600000', 100, 10, trade_date='2026-07-06')
        self.assertAlmostEqual(trade['dividend_tax'], 10.0)
        self.assertAlmostEqual(p.cash, 99979.0)
        self.assertNotIn('600000', p.positions)

    def test_retained_or_added_no_tax(self):
        p = Portfolio(100000)
        p.buy_shares('600000', 100, 10, trade_date='2026-05-06')
        p.buy_shares('600000', 100, 10, trade_date='2026-06-06')
        self.assertEqual(p.positions['600000']['shares'], 200)
        self.assertEqual(len(p.positions['600000']['lots']), 2)

    def test_partial_sale_uses_fifo_lot(self):
        p = Portfolio(100000)
        p.buy_shares('600000', 100, 10, trade_date='2026-05-06')
        p.buy_shares('600000', 100, 10, trade_date='2026-06-06')
        with patch('portfolio.tax_for_lot', return_value=5.0) as mocked:
            trade = p.sell_shares('600000', 100, 10, trade_date='2026-07-06')
        self.assertAlmostEqual(trade['dividend_tax'], 5.0)
        self.assertEqual(p.positions['600000']['shares'], 100)
        self.assertEqual(len(p.positions['600000']['lots']), 1)
        self.assertEqual(mocked.call_args[0][1], 100)  # 卖出的 100 股属于第一批

    def test_tax_disabled_no_tax(self):
        old = config.DIVIDEND_TAX_ENABLED
        try:
            config.DIVIDEND_TAX_ENABLED = False
            p = Portfolio(100000)
            p.buy_shares('600000', 100, 10, trade_date='2026-05-06')
            trade = p.sell_shares('600000', 100, 10, trade_date='2026-07-06')
            self.assertEqual(trade['dividend_tax'], 0.0)
        finally:
            config.DIVIDEND_TAX_ENABLED = old


if __name__ == '__main__':
    unittest.main(verbosity=2)
