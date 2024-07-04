import json
import datetime
import websocket
import logging
from queue import Queue

class DataCollector:
    def __init__(self, queue):
        self.queue = queue
        self.message_count = 0

    def on_message(self, ws, message):
        data = json.loads(message)
        if 'data' in data:
            for item in data['data']:
                if item['instId'] == 'BTC-USDT-SWAP':
                    current_time = datetime.datetime.utcnow()
                    time_str = current_time.strftime('%Y-%m-%d %H:%M:%S')
                    self.message_count += 1
                    logging.info(f"{time_str}: YES 第{self.message_count}条")
                    item['timestamp'] = current_time.strftime('%Y-%m-%d %H:%M:%S')
                    self.queue.put(item)

    def on_error(self, ws, error):
        logging.error(f"WebSocket错误: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        logging.info("WebSocket已关闭")
        if close_status_code or close_msg:
            logging.info(f"Close status code: {close_status_code}, Close message: {close_msg}")

    def on_open(self, ws):
        logging.info("WebSocket已连接")
        subscribe_message = {
            "op": "subscribe",
            "args": [{"channel": "tickers", "instId": "BTC-USDT-SWAP"}]
        }
        ws.send(json.dumps(subscribe_message))

    def start(self):
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            "wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999",
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open
        )
        ws.run_forever()
