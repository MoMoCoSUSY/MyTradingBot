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
EMA_PERIOD = 150
RSI_BUY_LEVEL = 40
ATR_MULTIPLIER = 4
INITIAL_CASH = 100000

# ================= 2. 数据准备 =================
def get_data():
    daily_data = {}
    intraday_data = {}
    print("正在拉取多周期数据...")
    for t in TICKERS:
        d = yf.download(t, period='2y', interval='1d', progress=False)
        i = yf.download(t, period='60d', interval='15m', progress=False)
        
        if d.empty or i.empty:
            print(f"  {t} ❌ 数据下载失败")
            return []
        
        for df in [d, i]:
            df.index = df.index.tz_localize(None)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        # 指标计算
        d['EMA'] = d['Close'].ewm(span=EMA_PERIOD, adjust=False).mean()
        i['RSI'] = 100 - (100 / (1 + (i['Close'].diff().where(i['Close'].diff() > 0, 0).ewm(com=13).mean() / 
                                      -i['Close'].diff().where(i['Close'].diff() < 0, 0).ewm(com=13).mean())))
        # 简化版 ATR
        i['ATR'] = (i['High'] - i['Low']).rolling(14).mean()
        
        daily_data[t] = d
        intraday_data[t] = i
        time.sleep(0.5)
    return daily_data, intraday_data

# ================= 3. 模拟引擎 =================
# 1. 准备数据
daily, intraday = get_data()
pm = PositionManager(total_cash=INITIAL_CASH, num_slots=len(TICKERS))

# 对齐时间轴 (以 QQQ 的 15min 时间戳为基准)
timeline = intraday['QQQ'].index
equity_curve = []

# 2. 动态参数字典初始化
TICKER_PARAMS = {}
print("\n[PARAMETER OPTIMIZATION] 正在计算自适应阈值...")

for t in TICKERS:
    # 获取动态阈值
    adaptive_rsi = ThresholdOptimizer.get_adaptive_threshold(intraday[t], base_level=RSI_BUY_LEVEL)
    TICKER_PARAMS[t] = {
        'rsi_threshold': adaptive_rsi,
        'atr_multiplier': 4.0 # 可针对性增加波动率补偿
    }
    print(f"  └─ {t:6}: 推荐 RSI 阈值 = {adaptive_rsi}")
    
print("开始多股并行资金管理回测...")

for t_point in timeline:
    current_prices = {}
    
    for t in TICKERS:
        if t_point not in intraday[t].index: continue
        
        bar = intraday[t].loc[t_point]
        prev_bar = intraday[t].shift(1).loc[t_point]
        current_prices[t] = bar['Close']
        
        # --- 1. 持仓管理 (止损/追踪) ---
        if t in pm.positions:
            # 更新追踪止损位
            new_stop = bar['Close'] - (bar['ATR'] * ATR_MULTIPLIER)
            pm.update_trailing_stop(t, new_stop)
            
            # 检查是否触碰止损
            if bar['Close'] <= pm.positions[t]['trailing_stop']:
                pm.close(t, bar['Close'], t_point)
        
        # --- 2. 信号扫描 ---
        else:
            try:
                day_data = daily[t].loc[daily[t].index <= t_point.normalize()].iloc[-1]
                
                # 核心信号判断
                # 第一层：RSI 择时触发 (从超卖区反弹)
                threshold = TICKER_PARAMS[t]['rsi_threshold']
                if prev_bar['RSI'] < threshold and bar['RSI'] >= threshold:
                    # 记录信号（审计日志）
                    pm.signal_log.append({
                        'Time': t_point,
                        'Ticker': t,
                        'Price': round(bar['Close'], 2),
                        'Daily_EMA': round(day_data['EMA'], 2),
                        'RSI': round(bar['RSI'], 2),
                        'Trend_OK': bar['Close'] > day_data['EMA'],
                        'Slot_Available': pm.can_open(t)
                    })
                    
                    # 第二层：战略过滤 (必须在日线 EMA 上方，确保大趋势向上)
                    if bar['Close'] > day_data['EMA']:
                        # 第三层：价格确认 (当前收盘价突破前一根15min K线高点，确认动量翻转)
                        if bar['Close'] > prev_bar['High']and pm.can_open(t):
                            initial_stop = bar['Close'] - (bar['ATR'] * ATR_MULTIPLIER)
                            pm.open(t, bar['Close'], initial_stop, t_point)
            except: continue

    equity_curve.append(pm.get_total_value(current_prices))

# # ================= 4. 统计总结 =================
# final_df = pd.DataFrame(pm.closed_trades)
# print("\n" + "="*40)
# print(f"最终账户价值: ${pm.get_total_value(current_prices):.2f}")
# print(f"总交易次数: {len(final_df)}")
# if not final_df.empty:
#     win_rate = len(final_df[final_df['pnl_pct'] > 0]) / len(final_df)
#     print(f"总胜率: {win_rate:.2%}")
#     print(f"平均每笔收益: {final_df['pnl_pct'].mean():.4%}")
# print("="*40)

# ================= 4. 统计总结 =================
print("\n" + "="*50)
print("              信号捕捉与丢失分析")
print("="*50)

df_signals = pd.DataFrame(pm.signal_log)
if not df_signals.empty:
    total_sig = len(df_signals)
    # 统计拦截原因
    trend_blocked = len(df_signals[df_signals['Trend_OK'] == False])
    slot_blocked = len(df_signals[(df_signals['Trend_OK'] == True) & (df_signals['Slot_Available'] == False)])
    executed = len(pm.closed_trades) + len(pm.positions)
    
    print(f"总计触发信号: {total_sig} 次")
    print(f"  └─ 趋势不符(价格在EMA下): {trend_blocked} 次")
    print(f"  └─ 资金/坑位不足拦截: {slot_blocked} 次")
    print(f"  └─ 成功入场: {executed} 次")
    
    # 展示最近的 10 条丢失信号（可选）
    lost_signals = df_signals[(df_signals['Trend_OK'] == True) & (df_signals['Slot_Available'] == False)]
    if not lost_signals.empty:
        print("\n[最近因坑位不足丢失的信号]:")
        print(lost_signals.tail(10).to_string(index=False))
    df_signals.to_csv("lost_signals_details.csv", index=False)
    print(f"\n✅ 完整丢失信号已保存至: lost_signals_details.csv")
        
# ================= 4. 统计总结 =================
print("\n" + "="*50)
print("              单笔交易明细报表")
print("="*50)

if pm.closed_trades:
    # 转换为 DataFrame
    df_trades = pd.DataFrame(pm.closed_trades)
    
    # 调整列顺序，使其更符合阅读习惯
    cols = ['Ticker', 'Buy Time', 'Buy Price', 'Close Time', 'Close Price', 
            'Total Buy Cost', 'Total Close Value', 'PnL %', 'PnL Cash']
    df_trades = df_trades[cols]
    
    # # 在控制台打印前 20 笔（如果太多的话）
    # print(df_trades.to_string(index=False))
    
    # 自动保存到本地，方便你用 Excel 打开深度分析
    df_trades.to_csv("backtest_trade_details.csv", index=False)
    print(f"\n✅ 完整交易记录已保存至: backtest_trade_details.csv")
else:
    print("未发现符合条件的交易记录。")

print("="*50)
print(f"最终账户总价值: ${pm.get_total_value(current_prices):.2f}")


plt.figure(figsize=(10, 6))
plt.plot(equity_curve)
plt.title("Account Equity Curve - v2.0")
plt.xlabel("15min Bars")
plt.ylabel("Total Asset ($)")
plt.grid(True)
plt.show()
