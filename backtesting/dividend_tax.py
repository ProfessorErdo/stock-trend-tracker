"""A股红利税：按批次持股期，在卖出时结算。

规则（个人投资者，差别化）：
- 持股 <= 1 个月：20%
- 1 个月 < 持股 <= 1 年：10%
- 持股 > 1 年：0%

税基 = 该批次股份在持有期间收到的现金分红（每股合计，税前）；
只在卖出时对“卖出的股份”征税。保留/加仓不触发。
"""
import pandas as pd
import config


def holding_period_rate(entry_date, sale_date) -> float:
    """按自然月/年判断税率；返回 0.20 / 0.10 / 0.0。"""
    if entry_date is None or sale_date is None:
        return 0.0
    entry = pd.Timestamp(entry_date)
    sale = pd.Timestamp(sale_date)
    if pd.isna(entry) or pd.isna(sale) or sale < entry:
        return 0.0
    if sale <= entry + pd.DateOffset(months=1):
        return float(config.DIVIDEND_TAX_SHORT_RATE)
    if sale <= entry + pd.DateOffset(years=1):
        return float(config.DIVIDEND_TAX_MEDIUM_RATE)
    return float(config.DIVIDEND_TAX_LONG_RATE)


def dividends_per_share(stock_code: str, entry_date, sale_date) -> float:
    """该批次持有期间（entry < ex_date <= sale）的每股现金分红合计。"""
    from stock_selector import _load_dividend_panel
    panel = _load_dividend_panel()
    g = panel.get(str(stock_code).zfill(6))
    if g is None or len(g) == 0:
        return 0.0
    entry = pd.Timestamp(entry_date)
    sale = pd.Timestamp(sale_date)
    sub = g[(g["ex_date"] > entry) & (g["ex_date"] <= sale)]
    if sub.empty:
        return 0.0
    return float(sub["cash_div_per_10"].sum() / 10.0)


def tax_for_lot(stock_code: str, shares: int, entry_date, sale_date) -> float:
    """单批次卖出时的红利税。"""
    if not getattr(config, "DIVIDEND_TAX_ENABLED", False):
        return 0.0
    if shares <= 0:
        return 0.0
    rate = holding_period_rate(entry_date, sale_date)
    if rate <= 0:
        return 0.0
    dps = dividends_per_share(stock_code, entry_date, sale_date)
    if dps <= 0:
        return 0.0
    return float(shares * dps * rate)
