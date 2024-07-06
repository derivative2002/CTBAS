import json
import datetime
import logging
import asyncio
import websockets
from queue import Queue

class DataCollector:
    def __init__(self, queue):
        self.queue = queue
        self.message_count = 0

    async def on_message(self, message):
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

    async def start(self):
        uri = "wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999"
        async with websockets.connect(uri) as websocket:
            subscribe_message = {
                "op": "subscribe",
                "args": [{"channel": "tickers", "instId": "BTC-USDT-SWAP"}]
            }
            await websocket.send(json.dumps(subscribe_message))
            async for message in websocket:
                await self.on_message(message)
