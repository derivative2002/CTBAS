import json
import datetime
import logging
import asyncio
import websockets
from queue import Queue, Empty
import hmac
import base64
import hashlib
from config import api_key, secret_key, passphrase

class DataCollector:
    def __init__(self, queue):
        self.queue = queue
        self.message_count = 0
        self.reconnect_delay = 5  # 重连延迟时间(秒)
        self.last_message_time = datetime.datetime.utcnow()
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.private_uri = "wss://ws.okx.com:8443/ws/v5/private"
        self.public_uri = "wss://ws.okx.com:8443/ws/v5/public"
        self.last_price = None
        self.price_threshold = 0.1  # 0.1% 的价格变动阈值

        # 设置日志
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s - %(levelname)s - %(message)s')

    def get_timestamp(self):
        return str(int(datetime.datetime.now().timestamp()))

    def get_signature(self, timestamp, method, request_path, body):
        message = timestamp + method + request_path + body
        mac = hmac.new(bytes(self.secret_key, encoding='utf8'), bytes(message, encoding='utf-8'), digestmod='sha256')
        d = mac.digest()
        return base64.b64encode(d).decode()

    def login_params(self):
        timestamp = self.get_timestamp()
        sign = self.get_signature(timestamp, 'GET', '/users/self/verify', '')

        return {
            "op": "login",
            "args": [{
                "apiKey": self.api_key,
                "passphrase": self.passphrase,
                "timestamp": timestamp,
                "sign": sign
            }]
        }

    def subscribe_private_params(self):
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
                }
            ]
        }

    def subscribe_public_params(self):
        return {
            "op": "subscribe",
            "args": [
                {
                    "channel": "tickers",
                    "instId": "BTC-USDT-SWAP"
                }
            ]
        }

    async def on_message(self, message):
        if message == "pong":
            logging.debug("Received pong message")
            return

        data = json.loads(message)

        if 'event' in data:
            if data['event'] == 'subscribe':
                logging.info(f"成功订阅: {data}")
            elif data['event'] == 'error':
                logging.error(f"订阅错误: {data}")
        elif 'arg' in data:
            channel = data['arg']['channel']
            if channel == 'account':
                self.handle_account_update(data)
            elif channel == 'positions':
                self.handle_positions_update(data)
            elif channel == 'balance_and_position':
                self.handle_balance_and_position_update(data)
            elif channel == 'tickers':
                self.handle_tickers_update(data)
        else:
            logging.warning(f"收到未预期的消息格式: {message}")

    def handle_account_update(self, data):
        account_data = data['data'][0]
        logging.info(f"账户更新: 总权益 = {account_data['totalEq']} USDT")
        self.queue.put(("account", account_data))

    def handle_positions_update(self, data):
        positions = data['data']
        if positions:
            for position in positions:
                logging.info(f"持仓: {position['instId']}, 数量: {position['pos']}")
                self.queue.put(("position", position))
        else:
            logging.info("无开放持仓")
            self.queue.put(("position", None))

    def handle_balance_and_position_update(self, data):
        update_data = data['data'][0]
        logging.info("余额和持仓更新:")
        for balance in update_data['balData']:
            logging.info(f"  {balance['ccy']}: {balance['cashBal']}")
        self.queue.put(("balance_and_position", update_data))

    def handle_tickers_update(self, data):
        for item in data['data']:
            if item['instId'] == 'BTC-USDT-SWAP':
                current_price = float(item.get('last', 'N/A'))
                if self.last_price is None or abs(current_price - self.last_price) / self.last_price > self.price_threshold:
                    self.last_price = current_price
                    self.queue.put(("ticker", item))

    async def send_heartbeat(self, websocket):
        while True:
            try:
                await websocket.send("ping")
                await asyncio.sleep(20)  # 每20秒发送一次心跳
            except:
                break

    async def start(self):
        while True:
            try:
                await asyncio.gather(
                    self.start_private_connection(),
                    self.start_public_connection()
                )
            except Exception as e:
                logging.error(f"连接错误: {e}")
                await asyncio.sleep(self.reconnect_delay)

    async def start_private_connection(self):
        async with websockets.connect(self.private_uri) as websocket:
            logging.info("私有WebSocket连接已建立")

            # 登录和订阅私有频道
            await websocket.send(json.dumps(self.login_params()))
            login_response = await websocket.recv()
            logging.info(f"登录响应: {login_response}")

            await websocket.send(json.dumps(self.subscribe_private_params()))
            logging.info("已发送私有频道订阅请求")

            heartbeat_task = asyncio.create_task(self.send_heartbeat(websocket))

            try:
                async for message in websocket:
                    await self.on_message(message)
            finally:
                heartbeat_task.cancel()

    async def start_public_connection(self):
        async with websockets.connect(self.public_uri) as websocket:
            logging.info("公共WebSocket连接已建立")

            # 订阅公共频道
            await websocket.send(json.dumps(self.subscribe_public_params()))
            logging.info("已发送公共频道订阅请求")

            heartbeat_task = asyncio.create_task(self.send_heartbeat(websocket))

            try:
                async for message in websocket:
                    await self.on_message(message)
            finally:
                heartbeat_task.cancel()

# 示例用法
if __name__ == "__main__":
    data_queue = Queue()
    collector = DataCollector(data_queue)

    async def print_queue_data():
        while True:
            try:
                data_type, data = data_queue.get_nowait()
                print(f"从队列获取的数据类型: {data_type}")
                print(f"数据内容: {data}")
            except Empty:
                await asyncio.sleep(1)

    async def main():
        collector_task = asyncio.create_task(collector.start())
        print_task = asyncio.create_task(print_queue_data())
        await asyncio.gather(collector_task, print_task)

    asyncio.run(main())