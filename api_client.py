import json
import time
import hmac
import hashlib
import base64
import requests
from requests.exceptions import RequestException
from utils import get_timestamp


class APIClient:
    def __init__(self, api_key, secret_key, passphrase, base_url):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.base_url = base_url
        self.session = requests.Session()

    def sign_message(self, timestamp, method, request_path, body=''):
        message = timestamp + method + request_path + body
        hmac_key = bytes(self.secret_key, 'utf-8')
        message_bytes = bytes(message, 'utf-8')
        signature = hmac.new(hmac_key, message_bytes, hashlib.sha256).digest()
        signature_base64 = base64.b64encode(signature).decode()
        return signature_base64

    def get_data_with_retry(self, endpoint, method="GET", params=None, data=None, max_retries=5, delay=2):
        url = self.base_url + endpoint
        for attempt in range(max_retries):
            try:
                timestamp = get_timestamp()
                headers = {
                    'Content-Type': 'application/json',
                    'OK-ACCESS-KEY': self.api_key,
                    'OK-ACCESS-SIGN': self.sign_message(timestamp, method, endpoint, json.dumps(data) if data else ''),
                    'OK-ACCESS-TIMESTAMP': timestamp,
                    'OK-ACCESS-PASSPHRASE': self.passphrase,
                    'x-simulated-trading': '1',
                }
                if method == "GET":
                    response = self.session.get(url, headers=headers, params=params, timeout=10)
                else:
                    response = self.session.post(url, headers=headers, json=data, timeout=10)
                response.raise_for_status()
                return response.json()
            except RequestException as e:
                print(f"请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                print(f"请求详情: URL={url}, 方法={method}, 参数={params}, 数据={data}")
                if attempt < max_retries - 1:
                    time.sleep(delay)
        print("所有重试都失败了")
        return None

    def get_account_balance(self):
        endpoint = "/api/v5/account/balance?ccy=USDT"
        response = self.get_data_with_retry(endpoint)
        if response and 'data' in response:
            return float(response['data'][0]['details'][0]['cashBal'])
        return None

    def get_current_price(self):
        endpoint = "/api/v5/market/ticker?instId=BTC-USDT-SWAP"
        response = self.get_data_with_retry(endpoint)
        if response and 'data' in response:
            return float(response['data'][0]['last'])
        return None

    def get_kline_data(self, limit):
        endpoint = "/api/v5/market/candles"
        params = {
            'instId': 'BTC-USDT-SWAP',
            'bar': '1m',
            'limit': str(limit)
        }
        return self.get_data_with_retry(endpoint, params=params)

    def get_symbol_info(self, symbol):
        endpoint = f"/api/v5/public/instruments"
        params = {
            'instType': 'SWAP',
            'instId': symbol
        }
        return self.get_data_with_retry(endpoint, params=params)
