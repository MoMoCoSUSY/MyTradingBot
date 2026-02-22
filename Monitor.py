import yfinance as yf
import pandas as pd
import schedule
import time
import random
import json
import os  # 导入 os 库来设置环境变量
from datetime import datetime

# ================= 配置加载 =================
def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)

CONFIG = load_config()

# 从 CONFIG 中提取参数
WATCHLIST = CONFIG['watchlist']
RSI_PERIOD = CONFIG['rsi_period']
RSI_OVERSOLD = CONFIG['rsi_oversold']
RSI_OVERBOUGHT = CONFIG['rsi_overbought']
PROXY_URL = CONFIG.get('proxy_url') # 使用 .get 防止 key 不存在报错

# 设置代理
if PROXY_URL:
    os.environ['HTTP_PROXY'] = PROXY_URL
    os.environ['HTTPS_PROXY'] = PROXY_URL

# ================= 核心算法 =================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0))
    loss = (-delta.where(delta < 0, 0))
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ================= 监控逻辑 (更新索引修复) =================
def fetch_and_check():
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[{now}] 正在扫描市场信号...")
    
    for ticker in WATCHLIST:
        try:
            time.sleep(random.uniform(2, 5)) 
            
            df = yf.download(
                ticker, 
                period='5d', 
                interval='15m', 
                progress=False
            )
            
            # --- 拍扁多重索引列名 ---
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # 使用 .empty 明确判断
            if df.empty or len(df) < RSI_PERIOD:
                print(f"⚠️ {ticker}: 无数据")
                continue

            # 计算 RSI
            df['RSI'] = calculate_rsi(df['Close'], RSI_PERIOD)
            
            # 获取最新有效行 (排除 NaN)
            valid_df = df.dropna(subset=['RSI'])
            if valid_df.empty:
                continue
                
            current_data = valid_df.iloc[-1]
            current_rsi = current_data['RSI']
            current_price = current_data['Close']

            status = "OK"
            if current_rsi <= RSI_OVERSOLD:
                status = "⚠️ [超卖 - 买入信号]"
            elif current_rsi >= RSI_OVERBOUGHT:
                status = "📢 [超买 - 卖出信号]"
            
            print(f"{ticker:5} | 价格: ${current_price:8.2f} | RSI: {current_rsi:6.2f} | {status}")

        except Exception as e:
            print(f"❌ {ticker} 错误: {e}")

# ================= 运行区 =================
if __name__ == "__main__":
    print(f"🚀 机器人已启动。当前监控: {WATCHLIST}")    
    fetch_and_check()
    schedule.every(15).minutes.do(fetch_and_check)

    while True:
        schedule.run_pending()
        time.sleep(1)