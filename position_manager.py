# position_manager.py

class PositionManager:
        
    def __init__(self, total_cash, num_slots=5):
        self.initial_cash = total_cash
        self.current_cash = total_cash
        self.num_slots = num_slots
        self.slot_size = total_cash / num_slots
        self.positions = {}  # 结构: {ticker: {buy_price, shares, trailing_stop, entry_value}}
        self.closed_trades = [] # 记录已完成的交易数据
        self.signal_log = []  # 新增：记录所有触发过的信号
        
    def can_open(self, ticker):
        """是否有空位且未持有该股"""
        return len(self.positions) < self.num_slots and ticker not in self.positions

    def open(self, ticker, price, trailing_stop, time):
        """开仓逻辑"""
        shares = self.slot_size // price
        if shares <= 0: return False
        
        cost = shares * price
        self.positions[ticker] = {
            'buy_price': price,
            'shares': shares,
            'trailing_stop': trailing_stop,
            'entry_value': cost,
            'entry_time': time
        }
        self.current_cash -= cost
        return True

    def update_trailing_stop(self, ticker, new_stop):
        """动态更新追踪止损位（只升不降）"""
        if ticker in self.positions:
            self.positions[ticker]['trailing_stop'] = max(self.positions[ticker]['trailing_stop'], new_stop)

    def close(self, ticker, price, time):
            """平仓逻辑"""
            if ticker in self.positions:
                pos = self.positions.pop(ticker)
                exit_value = pos['shares'] * price
                self.current_cash += exit_value
                
                pnl_pct = (price - pos['buy_price']) / pos['buy_price']
                
                # --- 增加详细记录项 ---
                self.closed_trades.append({
                    'Ticker': ticker,
                    'Buy Price': round(pos['buy_price'], 2),
                    'Buy Time': pos['entry_time'],
                    'Close Price': round(price, 2),
                    'Close Time': time,
                    'Total Buy Cost': round(pos['entry_value'], 2),
                    'Total Close Value': round(exit_value, 2),
                    'PnL %': f"{pnl_pct:.2%}",
                    'PnL Cash': round(exit_value - pos['entry_value'], 2)
                })
                return True
            return False

    def get_total_value(self, current_prices):
        """计算当前账户总价值 (现金 + 持仓市值)"""
        market_value = sum(self.positions[t]['shares'] * current_prices.get(t, self.positions[t]['buy_price']) for t in self.positions)
        return self.current_cash + market_value