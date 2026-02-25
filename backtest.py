import yfinance as yf
import pandas as pd
import numpy as np
import json
import os  # 导入 os 库来设置环境变量

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
    
# --- 配置回测参数 ---
TICKERS = ['NVDA', 'AMD', 'AAPL', 'QQQ', 'MSFT']
EMA_CANDIDATES = [20, 50, 100, 150, 200]
RSI_PERIOD = 14
RSI_BUY_LEVEL = 35  # 稍微放宽一点以增加样本量

    
def run_backtest(ticker, ema_period):

    # 下载 60 天 15 分钟线数据
    df = yf.download(ticker, period='1y', interval='1d', progress=False, timeout=20)
    # 检查返回对象是否有效
    if df is None or df.empty:
        print(f"⚠️ {ticker}: 下载返回空值，跳过")
        return []

    # 3. 处理多重索引（yfinance v0.2.x 必备）
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    # 4. 再次检查 Close 列是否存在
    if 'Close' not in df.columns:
        print(f"⚠️ {ticker}: 缺少 Close 列数据")
        return []
    
    # 指标计算
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).ewm(com=RSI_PERIOD-1, min_periods=RSI_PERIOD).mean()
    loss = -delta.where(delta < 0, 0).ewm(com=RSI_PERIOD-1, min_periods=RSI_PERIOD).mean()
    df['RSI'] = 100 - (100 / (1 + gain/loss))
    df['EMA'] = df['Close'].ewm(span=ema_period, adjust=False).mean()
    
    # 模拟交易逻辑
    trades = []
    in_position = False
    buy_price = 0
    highest_price = 0  # 在循环外也定义一下，防止逻辑极端情况

    for i in range(1, len(df)):
        curr = df.iloc[i]
        prev = df.iloc[i-1]        
        
        # 买入条件：价格 > EMA 且 RSI 从下方穿过 35 (超卖反弹)
        if not in_position:
            if curr['Close'] > curr['EMA'] and prev['RSI'] < RSI_BUY_LEVEL and curr['RSI'] >= RSI_BUY_LEVEL:
                buy_price = curr['Close']
                highest_price = curr['Close']  # 买入时初始化最高价
                in_position = True
        
        elif in_position:
            # 更新持仓期间见到的最高价
            highest_price = max(highest_price, curr['High'])            
            # 计算从最高点回落的比例 (移动止损/追踪止损)
            drawdown = (highest_price - curr['Close']) / highest_price
            # 计算相对于买入价的损益
            return_pct = (curr['Close'] - buy_price) / buy_price
            
            # 策略：从高点回落 xx% 止盈离场，或硬性止损 xx%
            if drawdown >= 0.05 or return_pct <= -0.15:
                trades.append(return_pct)
                in_position = False
                highest_price = 0 # 重置
                
    return trades

# --- 执行批量对比 ---
results = []
print(f"开始回测过去 365 天数据...")

for ema in EMA_CANDIDATES:
    all_returns = []
    for t in TICKERS:
        res = run_backtest(t, ema)
        all_returns.extend(res)
    
    if all_returns:
        win_rate = len([r for r in all_returns if r > 0]) / len(all_returns)
        avg_ret = np.mean(all_returns)
        results.append({
            "EMA_Period": ema,
            "Total_Trades": len(all_returns),
            "Win_Rate": f"{win_rate:.2%}",
            "Avg_Return": f"{avg_ret:.4%}"
        })

# 输出对比表
report = pd.DataFrame(results)
print("\n=== EMA 周期回测报告 ===")
print(report.to_string(index=False))