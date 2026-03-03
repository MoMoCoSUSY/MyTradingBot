import yfinance as yf
import pandas as pd
import numpy as np
import time
import json
import os  # 导入 os 库来设置环境变量
from datetime import datetime, timezone
import matplotlib.pyplot as plt

from position_manager import PositionManager
from threshold_optimizer import ThresholdOptimizer

# ================= 配置加载 =================
def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)
CONFIG = load_config()

PROXY_URL = CONFIG.get('proxy_url') # 使用 .get 防止 key 不存在报错
# 设置代理
if PROXY_URL:
    os.environ['HTTP_PROXY'] = PROXY_URL
    os.environ['HTTPS_PROXY'] = PROXY_URL

# ================= 1. 配置 =================
TICKERS = CONFIG['watchlist']
INITIAL_CASH = 100000
ATR_MULTIPLIER_INITIAL = 2.0  # 已根据建议从 3.5 收紧至 2.0
RSI_AMNESTY_LEVEL = 25       # 特赦入场阈值

# ================= 2. 数据准备 =================
def run_daily_backtest():
    data_dict = {}

    print("正在拉取数据...")
    for t in TICKERS:
        df = yf.download(t, period='2y', interval='1d', progress=False)
        df.index = df.index.tz_localize(None)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        # 计算指标
        df['EMA'] = df['Close'].ewm(span=150, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + (df['Close'].diff().where(df['Close'].diff() > 0, 0).ewm(com=13).mean() / 
                                      -df['Close'].diff().where(df['Close'].diff() < 0, 0).ewm(com=13).mean())))
        df['ATR'] = (df['High'] - df['Low']).rolling(14).mean()
        data_dict[t] = df

    pm = PositionManager(INITIAL_CASH, num_slots=len(TICKERS))
    equity_curve = []
    
    # 获取每个标的的自适应阈值
    ticker_params = {t: ThresholdOptimizer.get_adaptive_threshold(data_dict[t]) for t in TICKERS}
    
    # 统一时间轴
    timeline = data_dict['QQQ'].index[200:] # 跳过指标预热期

    for t_now in timeline:
        prices_snapshot = {}
        
        for t in TICKERS:
            df = data_dict[t]
            if t_now not in df.index: continue
            
            curr = df.loc[t_now]
            prev = df.shift(1).loc[t_now]
            prices_snapshot[t] = curr['Close']
            threshold = ticker_params[t]

            # 获取 EMA 50 作为中短期参考
            ema_50 = df['Close'].ewm(span=50, adjust=False).mean().loc[t_now]

            # --- 判定入场逻辑 ---
            if not pm.can_open(t):
                continue
            
            # 路径 A: 标准趋势入场 (EMA 150 支撑)
            trend_entry = (curr['Close'] > curr['EMA']) and (prev['RSI'] < threshold and curr['RSI'] >= threshold)
            
            # 路径 B: 特赦入场 (极端超卖超跌反弹)
            # 逻辑：RSI 曾跌破 25，且当前价格开始收复前日高点，不看均线
            amnesty_entry = (prev['RSI'] < 25) and (curr['Close'] > prev['High'])
            
            if (trend_entry or amnesty_entry):
                # 针对特赦入场，我们通常需要更窄的止损，因为这是逆势交易
                multiplier = 2.0 if amnesty_entry else 3.5
                init_stop = curr['Close'] - (curr['ATR'] * multiplier)
                
                pm.open(t, curr['Close'], init_stop, t_now)
                if amnesty_entry:
                    print(f"🚑 {t} 触发特赦入场 (RSI < 25) | 时间: {t_now.date()}")
        
        # ✅ 每一天结束时记录账户总价值     
        current_total_value = pm.get_total_value(prices_snapshot)
        equity_curve.append(current_total_value)

# ✅ 修改返回值：同时返回 PM 对象和 净值序列
    return pm, equity_curve, timeline, prices_snapshot

pm_result, equity_curve, timeline, prices_snapshot = run_daily_backtest()


import matplotlib.pyplot as plt
import seaborn as sns

# --- 强制探测点 ---
print(f"📊 探测到总持仓数量: {len(pm_result.positions)}")
print(f"📊 探测到已完成交易数量: {len(pm_result.closed_trades)}")

if len(pm_result.positions) > 0:
    print(f"⚠️ 发现未平仓头寸: {list(pm_result.positions.keys())}")
    # 打印其中一个持仓的止损位，看看是不是设得太远了
    first_ticker = list(pm_result.positions.keys())[0]
    pos = pm_result.positions[first_ticker]
    print(f"   [{first_ticker}] 买入价: {pos['buy_price']:.2f}, 当前止损位: {pos['trailing_stop']:.2f}")

if len(pm_result.closed_trades) == 0 and len(pm_result.positions) == 0:
    print("❌ 警告：回测期间完全没有买入信号，请检查入场逻辑或数据范围！")
    
# 1. 导出 CSV
if pm_result.closed_trades:
    df_trades = pd.DataFrame(pm_result.closed_trades)
    df_trades.to_csv("trade_details_final.csv", index=False)
    print("\n✅ 成交明细已导出")

# 2. 净值与回撤曲线
equity_series = pd.Series(equity_curve, index=timeline)
rolling_max = equity_series.cummax()
drawdown = (equity_series - rolling_max) / rolling_max

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True, gridspec_kw={'height_ratios': [3, 1]})
ax1.plot(timeline, equity_curve, color='#27ae60', label='Total Equity')
ax1.fill_between(timeline, INITIAL_CASH, equity_curve, where=(np.array(equity_curve) > INITIAL_CASH), color='green', alpha=0.1)
ax1.set_title("Strategy Performance Dashboard (Daily Pro v3.0)")
ax1.grid(True, alpha=0.2)

ax2.fill_between(timeline, drawdown, 0, color='#e74c3c', alpha=0.3)
ax2.set_ylabel("Drawdown %")
ax2.grid(True, alpha=0.2)
plt.show()

# 3. 综合收益分布图 (含持仓浮动盈亏)
all_returns = []
if pm_result.closed_trades:
    all_returns.extend([float(t['PnL %'].strip('%')) / 100 for t in pm_result.closed_trades])
for t, pos in pm_result.positions.items():
    unrealized = (last_prices[t] - pos['buy_price']) / pos['buy_price']
    all_returns.append(unrealized)

if all_returns:
    plt.figure(figsize=(10, 5))
    sns.histplot(all_returns, bins=20, kde=True, color='skyblue')
    plt.axvline(0, color='red', linestyle='--')
    plt.title("Return Distribution (Realized + Unrealized)")
    plt.show()

print(f"\n📊 最终资产: ${equity_curve[-1]:.2f}")
print(f"📊 最大回撤: {drawdown.min():.2%}")








