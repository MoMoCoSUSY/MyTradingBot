import requests
import json

def send_telegram_msg(message):

    try:
        # 1. 加载配置
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        token = config.get('telegram_token')
        chat_id = config.get('telegram_chat_id')
        proxy_url = config.get('proxy_url') # 获取代理地址
        
        if not token or not chat_id:
            print("❌ 错误：未在 config.json 中配置 Telegram 参数")
            return

        # 2. 构造请求地址和内容
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        
        # 3. 配置代理字典
        proxies = None
        if proxy_url:
            proxies = {
                "http": proxy_url,
                "https": proxy_url
            }
        
        # 4. 发送请求（传入 proxies 参数）
        response = requests.post(
            url, 
            json=payload, 
            proxies=proxies, 
            timeout=10
        )
        
        # 检查是否发送成功
        result = response.json()
        if not result.get("ok"):
            print(f"❌ Telegram 返回错误: {result.get('description')}")
        
        return result
        
    except Exception as e:
        print(f"❌ Telegram 发送异常: {e}")