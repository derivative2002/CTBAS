import json
import datetime
import logging
import asyncio
import websockets
from queue import Queue


async def send_heartbeat(websocket):
    while True:
        try:
            await websocket.send(json.dumps({"op": "ping"}))
            await asyncio.sleep(20)  # 每20秒发送一次心跳
        except:
            break


class DataCollector:
    def __init__(self, queue):
        self.queue = queue
        self.message_count = 0
        self.reconnect_delay = 5  # 重连延迟时间(秒)
        self.last_message_time = datetime.datetime.utcnow()

        # 设置日志
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s - %(levelname)s - %(message)s')

    async def on_message(self, message):
        data = json.loads(message)
        if 'event' in data:
            if data['event'] == 'subscribe':
                logging.info(f"成功订阅: {data}")
            elif data['event'] == 'error':
                logging.error(f"订阅错误: {data}")
        elif 'data' in data:
            for item in data['data']:
                if item['instId'] == 'BTC-USDT-SWAP':
                    current_time = datetime.datetime.utcnow()
                    time_str = current_time.strftime('%Y-%m-%d %H:%M:%S')
                    self.message_count += 1
                    self.last_message_time = current_time
                    logging.info(f"{time_str}: 收到 BTC-USDT-SWAP 数据 - 价格: {item.get('last', 'N/A')}")
                    item['timestamp'] = time_str
                    self.queue.put(item)
        else:
            logging.warning(f"收到未预期的消息格式: {message}")

    def is_connected(self):
        return self.message_count > 0 and (datetime.datetime.utcnow() - self.last_message_time).total_seconds() < 10

    async def start(self):
        uri = "wss://ws.okx.com:8443/ws/v5/public"
        while True:
            try:
                async with websockets.connect(uri) as websocket:
                    logging.info("WebSocket连接已建立")
                    subscribe_message = {
                        "op": "subscribe",
                        "args": [{"channel": "tickers", "instId": "BTC-USDT-SWAP"}]
                    }
                    await websocket.send(json.dumps(subscribe_message))
                    logging.info("已发送订阅消息")

                    # 添加心跳机制
                    heartbeat_task = asyncio.create_task(send_heartbeat(websocket))

                    async for message in websocket:
                        await self.on_message(message)

            except websockets.exceptions.ConnectionClosedError as e:
                logging.error(f"WebSocket连接已关闭: {e}")
                logging.info(f"将在{self.reconnect_delay}秒后重新连接...")
                await asyncio.sleep(self.reconnect_delay)
            except Exception as e:
                logging.error(f"发生错误: {e}")
                logging.info(f"将在{self.reconnect_delay}秒后重新连接...")
                await asyncio.sleep(self.reconnect_delay)
            finally:
                if 'heartbeat_task' in locals():
                    heartbeat_task.cancel()
                logging.info("WebSocket连接已关闭，准备重新连接")


# 示例用法
if __name__ == "__main__":
    data_queue = Queue()
    collector = DataCollector(data_queue)


    async def print_queue_data():
        while True:
            try:
                data = data_queue.get_nowait()
                print(f"从队列获取的数据: {data}")
            except Queue.Empty:
                await asyncio.sleep(1)


    async def main():
        collector_task = asyncio.create_task(collector.start())
        print_task = asyncio.create_task(print_queue_data())
        await asyncio.gather(collector_task, print_task)


    asyncio.run(main())
