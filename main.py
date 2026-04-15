import os
import re
import time
import requests
import hashlib
import hmac
from flask import Flask, request, jsonify
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

app = Flask(__name__)

# ================== 配置区（必须修改） ==================
APPID = "19038****96"          # 傻福腾讯 回调网址不备案还用不了 不给你们看
SECRET = "****"        # 傻福腾讯 回调网址不备案还用不了 不给你们看
#TOKEN = "暂时不需要"          # 从平台复制
ELECTRICITY_URL = "https://epay.sues.edu.cn/epay/h5/eleresult?sysid=4&roomid=7009&areaid=102&buildid=32"
# ======================================================

# 全局 access_token 缓存
ACCESS_TOKEN = None
TOKEN_EXPIRE = 0

def get_access_token():
    global ACCESS_TOKEN, TOKEN_EXPIRE
    if time.time() < TOKEN_EXPIRE:
        return ACCESS_TOKEN
    
    url = "https://bots.qq.com/app/getAppAccessToken"
    data = {"appId": APPID, "secret": SECRET}
    resp = requests.post(url, json=data, timeout=10)
    result = resp.json()
    ACCESS_TOKEN = result.get("access_token") or result.get("token")
    TOKEN_EXPIRE = time.time() + result.get("expires_in", 7200) - 60
    return ACCESS_TOKEN

def get_electricity():
    try:
        r = requests.get(ELECTRICITY_URL, timeout=15)
        r.encoding = "utf-8"
        match = re.search(r'剩余电量<br>([\d.]+)度', r.text)
        return float(match.group(1)) if match else None
    except:
        return None

def send_message(openid=None, group_openid=None, channel_id=None, content=""):
    """发送文本消息（单聊 / 群 / 频道）"""
    token = get_access_token()
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json"
    }
    
    payload = {"content": content, "msg_type": 0}
    
    if openid:  # 私聊 C2C
        url = f"https://bot.q.qq.com/v2/users/{openid}/messages"
    elif group_openid:  # 群
        url = f"https://bot.q.qq.com/v2/groups/{group_openid}/messages"
    elif channel_id:  # 频道
        url = f"https://bot.q.qq.com/channels/{channel_id}/messages"
    else:
        return
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        print("发送回复结果：", resp.json())
    except Exception as e:
        print("发送失败：", e)

# Webhook 验证（官方要求）
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    op = data.get("op")
    
    # 1. 平台验证请求（op=13）
    if op == 13:
        d = data.get("d", {})
        plain_token = d.get("plain_token")
        event_ts = d.get("event_ts")
        if not plain_token or not event_ts:
            return jsonify({"error": "invalid"}), 400
        
        # 使用 SECRET 生成 Ed25519 签名
        key = ed25519.SigningKey(SECRET.encode() + b'\x00' * (32 - len(SECRET.encode())))
        sign_input = f"{event_ts}{plain_token}".encode()
        signature = key.sign(sign_input).hex()
        
        return jsonify({"plain_token": plain_token, "signature": signature})
    
    # 2. 正常消息事件
    if op == 0:
        t = data.get("t")
        d = data.get("d", {})
        msg_content = d.get("content", "").strip()
        
        # 判断是否是电费指令（支持 /电费 或 电费）
        if "电费" in msg_content or msg_content == "/电费":
            remaining = get_electricity()
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            
            if remaining is None:
                reply = f"⚠️ 查询失败，请稍后再试\n时间：{now}"
            else:
                tip = "✅ 电量充足，继续冲！" if remaining > 100 else \
                      "⚠️ 电量中等，建议关注" if remaining > 50 else \
                      "🚨 电量不足！请尽快充值！"
                reply = f"""🏠 宿舍电费查询结果
房间：7009
剩余电量：{remaining} 度
{tip}

查询时间：{now}"""
            
            # 根据事件类型回复
            if t == "C2C_MESSAGE_CREATE":  # 私聊
                openid = d.get("author", {}).get("id")
                send_message(openid=openid, content=reply)
            elif t == "GROUP_AT_MESSAGE_CREATE":  # 群 @ 
                group_openid = d.get("group_openid")
                send_message(group_openid=group_openid, content=reply)
            elif t == "MESSAGE_CREATE":  # 频道
                channel_id = d.get("channel_id")
                send_message(channel_id=channel_id, content=reply)
    
    # 必须返回 op=12 ACK
    return jsonify({"op": 12}), 200

# 健康检查
@app.route('/')
def index():
    return "QQ机器人电费查询服务已启动 ✅"

if __name__ == "__main__":
    # 本地测试用 8080，正式部署改 443 或 80
    app.run(host="0.0.0.0", port=8080)
