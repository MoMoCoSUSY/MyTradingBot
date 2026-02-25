import yfinance as yf
import pandas as pd
import schedule
import time
import random
import json
import os  # 导入 os 库来设置环境变量
from datetime import datetime
from notifier import send_telegram_msg
import pandas_market_calendars as mcal
from datetime import datetime, timezone
import pytz

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
# 从配置中动态读取周期，如果不存在则默认使用 200
ema_p = CONFIG.get('ema_period', 200)
PROXY_URL = CONFIG.get('proxy_url') # 使用 .get 防止 key 不存在报错

# 设置代理
if PROXY_URL:
    os.environ['HTTP_PROXY'] = PROXY_URL
    os.environ['HTTPS_PROXY'] = PROXY_URL
    
# ================= 2. 交易时间网关 =================
def is_market_open():
    try:
        nyse = mcal.get_calendar('NYSE')
        now_utc = datetime.now(pytz.utc)
        schedule_df = nyse.schedule(start_date=now_utc, end_date=now_utc)
        if schedule_df.empty: return False
        return nyse.open_at_time(schedule_df, now_utc)
    except:
        return False
    
# ================= 核心算法 =================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0))
    loss = (-delta.where(delta < 0, 0))
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
    
def calculate_macd(series, fast=12, slow=26, signal=9):
    exp1 = series.ewm(span=fast, adjust=False).mean()
    exp2 = series.ewm(span=slow, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist
    
# ================= 监控逻辑 (更新索引修复) =================
def fetch_and_check():
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[{now}]扫描中...")
    
    for ticker in WATCHLIST:
        try:
            # 随机延迟防止被封 IP
            time.sleep(random.uniform(2, 5)) 

            # 下载最近 5 天 15 分钟 K 线
            df = yf.download(
                ticker, 
                period='59d', 
                interval='15m', 
                progress=False
            )
            
            # --- 拍扁多重索引列名 ---
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # 使用 .empty 明确判断
            if df.empty or len(df) < 200:
                print(f"⚠️ {ticker}: 无数据")
                continue
                
            # --- 指标计算 ---
            close = df['Close']
            df['RSI'] = calculate_rsi(close, CONFIG['rsi_period'])
            # 动态计算指标
            df['EMA_DYNAMIC'] = close.ewm(span=ema_p, adjust=False).mean()
            df['MACD'], _, df['MACD_Hist'] = calculate_macd(close)

            # --- 信号提取 ---
            last = df.iloc[-1]
            prev = df.iloc[-2]
            
            curr_price = float(last['Close'])
            curr_rsi = float(last['RSI'])
            # 信号逻辑中使用动态均线
            curr_ema = float(last['EMA_DYNAMIC'])
            curr_hist = float(last['MACD_Hist'])
            prev_hist = float(prev['MACD_Hist'])

            # --- 增强型交易逻辑 ---
            msg = ""
            
            # 1. 做多策略：趋势向上 (Price > EMA200) + RSI超卖 + MACD柱状图回升/金叉
            if curr_price > curr_ema:
                if curr_rsi <= RSI_OVERSOLD and curr_hist > prev_hist:
                    msg = (f"🚀 *[多头信号] {ticker}*\n"
                           f"🔹 价格: ${curr_price:.2f} (在EMA{ema_p}之上)\n"
                           f"🔹 RSI: {curr_rsi:.2f} (超卖回升)\n"
                           f"🔹 MACD: 柱状图转强")

            # 2. 做空策略：趋势向下 (Price < EMA200) + RSI超买 + MACD柱状图走弱/死叉
            elif curr_price < curr_ema:
                if curr_rsi >= RSI_OVERBOUGHT and curr_hist < prev_hist:
                    msg = (f"📉 *[空头信号] {ticker}*\n"
                           f"🔹 价格: ${curr_price:.2f} (在EMA{ema_p}之下)\n"
                           f"🔹 RSI: {curr_rsi:.2f} (超买拐头)\n"
                           f"🔹 MACD: 柱状图转弱")

            if msg:
                print(f"Bingo! {ticker} 触发复合信号")
                send_telegram_msg(msg)
            else:
                print(f"{ticker:5} | Price: {curr_price:7.2f} | RSI: {curr_rsi:5.2f} | 趋势: {'UP' if curr_price > curr_ema else 'DOWN'}")

        except Exception as e:
            print(f"❌ {ticker} 错误: {e}")

# ================= 运行区 =================
if __name__ == "__main__":
    print(f"🚀 机器人已启动。当前监控: {WATCHLIST}")    

    if is_market_open():
        print(f"   检查频率: 每 15 分钟") 
        # 启动先跑一次
        fetch_and_check()
        schedule.every(15).minutes.do(fetch_and_check)
        while True:
            schedule.run_pending()
            time.sleep(1)
    else:
        print(f"非交易时间，股票现价：")
        fetch_and_check()
