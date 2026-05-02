"""
投资组合状态管理模块
管理持仓、现金、交易执行及成本计算
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

import pandas as pd


class Portfolio:
    """A股投资组合状态管理类"""

    def __init__(self, initial_capital: float = config.INITIAL_CAPITAL):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = {}  # {code: {'shares': int, 'cost_price': float}}
        self.trade_history = []
        self.holding_history = []

    def _calc_commission(self, amount: float) -> float:
        """计算交易佣金"""
        return max(amount * config.COMMISSION_RATE, config.COMMISSION_MIN)

    def _calc_stamp_tax(self, amount: float) -> float:
        """计算印花税（仅卖出）"""
        return amount * config.STAMP_TAX_RATE

    def get_total_equity(self, prices: dict) -> float:
        """
        计算总资产净值
        prices: {code: current_price}
        """
        equity = self.cash
        for code, pos in self.positions.items():
            price = prices.get(code, pos['cost_price'])
            equity += pos['shares'] * price
        return equity

    def sell_shares(self, stock_code, shares, price, reason="调仓卖出") -> dict:
        """
        卖出股票
        """
        pos = self.positions.get(stock_code)
        if pos is None:
            return None

        actual_shares = min(shares, pos['shares'])
        if actual_shares <= 0:
            return None

        amount = actual_shares * price
        commission = self._calc_commission(amount)
        stamp_tax = self._calc_stamp_tax(amount)

        self.cash += amount - commission - stamp_tax
        pos['shares'] -= actual_shares

        trade = {
            'trade_date': None,
            'stock_code': stock_code,
            'direction': '卖出',
            'shares': actual_shares,
            'price': price,
            'amount': amount,
            'commission': round(commission, 2),
            'stamp_tax': round(stamp_tax, 2),
            'reason': reason,
        }
        self.trade_history.append(trade)

        if pos['shares'] <= 0:
            del self.positions[stock_code]

        return trade

    def buy_shares(self, stock_code, shares, price, reason="调仓买入") -> dict:
        """
        买入股票（整手取整，不足现金时计算最大可买手数）
        """
        if shares <= 0 or price <= 0:
            return None

        # 整手取整: floor(shares / 100) * 100
        shares = (shares // config.LOT_SIZE) * config.LOT_SIZE
        if shares <= 0:
            return None

        amount = shares * price
        commission = self._calc_commission(amount)
        total_cost = amount + commission

        # 现金不足，计算最大可买手数
        if total_cost > self.cash:
            max_amount = self.cash
            # Approximate: cash / (price * (1 + commission_rate)) then lot-round
            max_shares = int(max_amount / (price * (1 + config.COMMISSION_RATE)))
            max_shares = (max_shares // config.LOT_SIZE) * config.LOT_SIZE
            if max_shares <= 0:
                return None
            shares = max_shares
            amount = shares * price
            commission = self._calc_commission(amount)
            total_cost = amount + commission

        self.cash -= total_cost

        # 更新持仓：加权平均成本
        if stock_code in self.positions:
            old = self.positions[stock_code]
            total_shares = old['shares'] + shares
            old['cost_price'] = (old['cost_price'] * old['shares'] + price * shares) / total_shares
            old['shares'] = total_shares
        else:
            self.positions[stock_code] = {
                'shares': shares,
                'cost_price': price,
            }

        trade = {
            'trade_date': None,
            'stock_code': stock_code,
            'direction': '买入',
            'shares': shares,
            'price': price,
            'amount': amount,
            'commission': round(commission, 2),
            'stamp_tax': 0.0,
            'reason': reason,
        }
        self.trade_history.append(trade)
        return trade

    def calculate_target_positions(self, target_codes, total_equity, prices, can_buy, can_sell) -> dict:
        """
        生成调仓计划
        target_codes: list of codes to hold
        total_equity: current total equity
        prices: {code: price}
        can_buy: bool
        can_sell: bool
        """
        N = len(target_codes)
        sell_orders = []
        buy_orders = []

        # N == 0: 卖出所有可卖持仓
        if N == 0:
            if can_sell:
                for code, pos in list(self.positions.items()):
                    sell_orders.append((code, pos['shares']))
            return {'sell_orders': sell_orders, 'buy_orders': buy_orders}

        # Step 1: 卖出不在目标池中的持仓
        target_set = set(target_codes)
        if can_sell:
            for code, pos in list(self.positions.items()):
                if code not in target_set:
                    sell_orders.append((code, pos['shares']))

        # Step 2: 计算每只股票目标仓位价值
        if N >= config.MIN_FULL_POSITION_STOCKS:
            target_value = total_equity / N
        else:
            target_value = config.MAX_SINGLE_POSITION * total_equity

        # Step 3: 生成买入订单
        if can_buy:
            for code in target_codes:
                price = prices.get(code, 0)
                if price <= 0:
                    continue

                current_shares = 0
                if code in self.positions:
                    current_shares = self.positions[code]['shares']

                target_shares = int(target_value / price)
                target_shares = (target_shares // config.LOT_SIZE) * config.LOT_SIZE

                diff = target_shares - current_shares
                if diff > 0:
                    buy_orders.append((code, diff))

        return {'sell_orders': sell_orders, 'buy_orders': buy_orders}

    def snapshot_holdings(self, trade_date, prices) -> pd.DataFrame:
        """
        生成持仓快照 DataFrame
        """
        rows = []
        total_equity = self.get_total_equity(prices)

        for code, pos in self.positions.items():
            current_price = prices.get(code, pos['cost_price'])
            market_value = pos['shares'] * current_price
            weight = market_value / total_equity if total_equity > 0 else 0.0
            rows.append({
                'rebalance_date': trade_date,
                'stock_code': code,
                'shares': pos['shares'],
                'cost_price': pos['cost_price'],
                'current_price': current_price,
                'market_value': market_value,
                'weight': weight,
            })

        return pd.DataFrame(rows, columns=[
            'rebalance_date', 'stock_code', 'shares', 'cost_price',
            'current_price', 'market_value', 'weight'
        ])

    def get_daily_equity(self, prices) -> float:
        """等同于 get_total_equity"""
        return self.get_total_equity(prices)
