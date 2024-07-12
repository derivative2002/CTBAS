import websocket
import json
import time
import hmac
import base64
import hashlib

# API配置
api_key = '24aa38f5-ec66-436d-8ff9-840587e40e9d'
secret_key = 'E0B524E2A8C6110413925411A7B6E114'
passphrase = '@BTL0202lwm0316'

# WebSocket连接URL
url = "wss://ws.okx.com:8443/ws/v5/private"


def get_timestamp():
    return str(int(time.time()))


def get_signature(timestamp, method, request_path, body, secret_key):
    message = timestamp + method + request_path + body
    mac = hmac.new(bytes(secret_key, encoding='utf8'), bytes(message, encoding='utf-8'), digestmod='sha256')
    d = mac.digest()
    return base64.b64encode(d).decode()


def login_params():
    timestamp = get_timestamp()
    method = 'GET'
    request_path = '/users/self/verify'
    body = ''
    sign = get_signature(timestamp, method, request_path, body, secret_key)

    return {
        "op": "login",
        "args": [{
            "apiKey": api_key,
            "passphrase": passphrase,
            "timestamp": timestamp,
            "sign": sign
        }]
    }


def subscribe_params():
    return {
        "op": "subscribe",
        "args": [
            {
                "channel": "account",
                "ccy": "BTC"
            },
            {
                "channel": "positions",
                "instType": "ANY"
            },
            {
                "channel": "balance_and_position"
            },
            {
                "channel": "liquidation-warning",
                "instType": "ANY"
            }
        ]
    }


def on_message(ws, message):
    print(f"Received message: {message}")
    data = json.loads(message)
    if 'event' in data and data['event'] == 'login':
        if data['code'] == '0':
            print("Login successful")
            # 登录成功后订阅频道
            subscribe_request = json.dumps(subscribe_params())
            ws.send(subscribe_request)
            print(f"Sent subscribe request: {subscribe_request}")
        else:
            print(f"Login failed: {data['msg']}")
    # 处理其他类型的消息...


def on_error(ws, error):
    print(f"Error: {error}")


def on_close(ws, close_status_code, close_msg):
    print(f"WebSocket connection closed: {close_status_code} - {close_msg}")


def on_open(ws):
    print("WebSocket connection opened")

    # 发送登录请求
    login_request = json.dumps(login_params())
    ws.send(login_request)
    print(f"Sent login request: {login_request}")


if __name__ == "__main__":
    websocket.enableTrace(True)
    ws = websocket.WebSocketApp(url,
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close,
                                on_open=on_open)

    ws.run_forever()