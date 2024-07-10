import asyncio
import websockets
import json
import time
import hmac
import hashlib
import base64
import logging
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from queue import Empty
from utils import get_timestamp
from config import api_key, secret_key, passphrase, TAKE_PROFIT, MA_PERIODS, ATR_PERIOD, ATR_MULTIPLIER, RISK_PERCENT, TREND_MA_PERIOD

class TradingStrategy(QThread):
    log_message_signal = pyqtSignal(str)
    update_balance_signal = pyqtSignal(str, float, float)
    update_position_info_signal = pyqtSignal(list)
    update_chart_signal = pyqtSignal(dict)

    def __init__(self, data_queue, analysis_window):
        super().__init__()
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.data_queue = data_queue
        self.analysis_window = analysis_window
        self.websocket = None
        self.paused = False
        self.initialize_strategy()

        # 设置日志
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    def initialize_strategy(self):
        self.open_positions = []
        self.strategy_status = "空闲"
        self.account_balance = None
        self.ma_values = np.zeros(len(MA_PERIODS))
        self.prev_ma_values = np.zeros(len(MA_PERIODS))
        self.trend_ma = 0
        self.atr = 0
        self.current_price = None
        self.open_price = None
        self.tick_value = 1  # 需要从交易所获取实际值
        self.tick_size = 0.5  # 需要从交易所获取实际值
        self.min_lot_size = 0.01  # 需要从交易所获取实际值
        self.max_lot_size = 100  # 需要从交易所获取实际值
        self.step_lot_size = 0.01  # 需要从交易所获取实际值

    def log_and_update(self, message, level=logging.INFO):
        self.logger.log(level, message)
        self.log_message_signal.emit(message)

    def sign_message(self, timestamp, method, request_path, body=''):
        message = timestamp + method + request_path + body
        hmac_key = bytes(self.secret_key, 'utf-8')
        message_bytes = bytes(message, 'utf-8')
        signature = hmac.new(hmac_key, message_bytes, hashlib.sha256).digest()
        signature_base64 = base64.b64encode(signature).decode()
        return signature_base64

    async def initialize_websocket(self):
        uri = "wss://wspap.okx.com:8443/ws/v5/private"
        headers = {"x-simulated-trading": "1"}
        try:
            self.websocket = await asyncio.wait_for(websockets.connect(uri, extra_headers=headers), timeout=30)
            self.log_and_update("WebSocket连接已建立")
            if await self.login():
                await self.subscribe_channels()
            else:
                raise Exception("登录失败")
        except asyncio.TimeoutError:
            self.log_and_update("WebSocket连接超时", logging.ERROR)
        except Exception as e:
            self.log_and_update(f"WebSocket连接失败: {str(e)}", logging.ERROR)

    async def login(self):
        max_retries = 3
        for attempt in range(max_retries):
            timestamp = get_timestamp()
            sign = self.sign_message(timestamp, 'GET', '/users/self/verify', '')
            login_message = {
                "op": "login",
                "args": [{
                    "apiKey": self.api_key,
                    "passphrase": self.passphrase,
                    "timestamp": timestamp,
                    "sign": sign
                }]
            }
            await self.websocket.send(json.dumps(login_message))
            response = await self.websocket.recv()
            self.log_and_update(f"登录响应: {response}")

            response_data = json.loads(response)
            if response_data.get('event') == 'login':
                self.log_and_update("登录成功")
                return True
            elif response_data.get('code') == '60004':  # 无效时间戳
                self.log_and_update(f"无效时间戳。重试中... (尝试 {attempt + 1}/{max_retries})")
                await asyncio.sleep(1)  # 等待1秒后重试
            else:
                self.log_and_update(f"登录失败: {response_data.get('msg')}")
                return False

        self.log_and_update("达到最大重试次数。登录失败。")
        return False

    async def subscribe_channels(self):
        subscribe_message = {
            "op": "subscribe",
            "args": [
                {"channel": "account", "ccy": "USDT"},
                {"channel": "positions", "instId": "BTC-USDT-SWAP"},
                {"channel": "orders", "instId": "BTC-USDT-SWAP"},
                {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
                {"channel": "candle1m", "instId": "BTC-USDT-SWAP"}
            ]
        }
        await self.websocket.send(json.dumps(subscribe_message))
        self.log_and_update("已发送频道订阅消息")

    async def handle_message(self, message):
        self.log_and_update(f"收到消息: {message}")
        if 'event' in message:
            if message['event'] == 'subscribe':
                self.log_and_update(f"成功订阅 {message['arg']['channel']} 频道")
        elif 'data' in message:
            channel = message['arg']['channel']
            if channel == 'account':
                self.handle_account_update(message['data'])
            elif channel == 'positions':
                self.handle_position_update(message['data'])
            elif channel == 'orders':
                self.handle_order_update(message['data'])
            elif channel == 'tickers':
                self.handle_ticker_update(message['data'])
            elif channel == 'candle1m':
                self.handle_kline_data(message['data'])
        else:
            self.log_and_update(f"未处理的消息类型: {message}")

    def handle_account_update(self, data):
        if data and len(data) > 0:
            details = data[0].get('details', [])
            if details and len(details) > 0:
                self.account_balance = float(details[0].get('availBal', 0))
                self.update_balance()

    def handle_position_update(self, data):
        self.open_positions = data
        self.update_positions()

    def handle_order_update(self, data):
        self.log_and_update(f"订单更新: {data}")

    def handle_ticker_update(self, data):
        self.current_price = float(data[0]['last'])
        self.log_and_update(f"当前价格更新为: {self.current_price}")
        self.check_and_execute_strategy()

    def update_balance(self):
        positions_value, floating_profit = self.get_open_positions_value()
        total_value = self.account_balance + floating_profit
        self.update_balance_signal.emit("USDT", self.account_balance, floating_profit)

    def get_open_positions_value(self):
        floating_profit = 0
        for position in self.open_positions:
            if self.current_price is None:
                continue
            if position['posSide'] == 'long':
                profit = (self.current_price - float(position['avgPx'])) * float(position['pos'])
            else:  # short
                profit = (float(position['avgPx']) - self.current_price) * float(position['pos'])
            floating_profit += profit
        return 0, floating_profit

    def update_positions(self):
        position_info = []
        for position in self.open_positions:
            position_info.append([
                position['posSide'],
                position['pos'],
                position['avgPx'],
                str(self.current_price),
                str(float(position['upl']))
            ])
        self.update_position_info_signal.emit(position_info)

    def handle_kline_data(self, data):
        self.log_and_update(f"收到K线数据: {data}")
        self.update_indicators(data)

    def update_indicators(self, kline_data):
        if len(kline_data) < max(max(MA_PERIODS), TREND_MA_PERIOD, ATR_PERIOD + 1):
            self.log_and_update(f"K线数据不足，当前数据量: {len(kline_data)}", logging.WARNING)
            return

        close_prices = np.array([float(k[4]) for k in kline_data])[::-1]
        high_prices = np.array([float(k[2]) for k in kline_data])[::-1]
        low_prices = np.array([float(k[3]) for k in kline_data])[::-1]

        for i, period in enumerate(MA_PERIODS):
            self.prev_ma_values[i] = self.ma_values[i]
            self.ma_values[i] = np.mean(close_prices[:period])

        self.trend_ma = np.mean(close_prices[:TREND_MA_PERIOD])
        self.atr = self.calculate_atr(high_prices, low_prices, close_prices, ATR_PERIOD)

        self.log_and_update(f"指标已更新 - MA值: {self.ma_values}, 趋势MA: {self.trend_ma}, ATR: {self.atr}")

    def calculate_atr(self, high_prices, low_prices, close_prices, period):
        tr = np.zeros(len(high_prices))
        tr[0] = high_prices[0] - low_prices[0]
        for i in range(1, len(high_prices)):
            tr[i] = max(high_prices[i] - low_prices[i],
                        abs(high_prices[i] - close_prices[i - 1]),
                        abs(low_prices[i] - close_prices[i - 1]))

        atr = np.zeros(len(tr))
        atr[0] = tr[0]
        for i in range(1, len(tr)):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        return atr[-1]

    def check_and_execute_strategy(self):
        if self.current_price is None or self.atr == 0:
            self.log_and_update("策略检查跳过: 当前价格或ATR不可用")
            return

        buy_condition, buy_reasons = self.check_buy_condition()
        sell_condition, sell_reasons = self.check_sell_condition()

        self.log_and_update(f"策略检查 - 买入条件: {buy_condition}, 卖出条件: {sell_condition}")

        if buy_condition:
            self.log_and_update(f"触发买入信号: {', '.join(buy_reasons)}")
            asyncio.create_task(self.open_position("buy"))
        elif sell_condition:
            self.log_and_update(f"触发卖出信号: {', '.join(sell_reasons)}")
            asyncio.create_task(self.open_position("sell"))
        else:
            self.log_and_update("没有交易信号")

    def check_buy_condition(self):
        if self.current_price is None or self.trend_ma == 0:
            return False, ["价格或趋势MA不可用"]

        if self.current_price <= self.trend_ma:
            return False, ["价格低于趋势MA"]

        for ma_value in self.ma_values:
            if self.current_price <= ma_value:
                return False, ["价格低于某些MA"]

        if self.prev_ma_values[2] is not None and self.current_price > self.prev_ma_values[2]:
            return False, ["前一收盘价未低于30日MA"]

        return True, ["满足所有买入条件"]

    def check_sell_condition(self):
        if self.current_price is None or self.trend_ma == 0:
            return False, ["价格或趋势MA不可用"]

        if self.current_price >= self.trend_ma:
            return False, ["价格高于趋势MA"]

        for ma_value in self.ma_values:
            if self.current_price >= ma_value:
                return False, ["价格高于某些MA"]

        if self.prev_ma_values[2] is not None and self.current_price < self.prev_ma_values[2]:
            return False, ["前一收盘价未高于30日MA"]

        return True, ["满足所有卖出条件"]

    def calculate_lot_size(self):
        if self.atr is None or self.atr == 0:
            self.log_and_update("ATR为零，无法计算交易量", logging.WARNING)
            return None

        risk_amount = self.account_balance * RISK_PERCENT / 100.0
        stop_loss_distance = ATR_MULTIPLIER * self.atr

        if self.current_price is None:
            self.log_and_update("当前价格不可用", logging.WARNING)
            return None

        risk_per_lot = stop_loss_distance / self.tick_size * self.tick_value
        lot_size = risk_amount / risk_per_lot

        lot_size = min(max(lot_size, self.min_lot_size), self.max_lot_size)
        lot_size = round(lot_size / self.step_lot_size) * self.step_lot_size

        self.log_and_update(f"计算的交易量: {lot_size} (账户余额: {self.account_balance}, "
                            f"风险金额: {risk_amount}, 止损距离: {stop_loss_distance})")

        return lot_size

    async def open_position(self, order_type):
        if self.account_balance is None or self.account_balance <= 0:
            self.log_and_update("账户余额不足", logging.WARNING)
            return

        lot_size = self.calculate_lot_size()
        if lot_size is None:
            return

        side = "buy" if order_type == "buy" else "sell"
        pos_side = "long" if order_type == "buy" else "short"

        self.open_price = self.current_price
        await self.send_order(side, pos_side, lot_size)
        self.log_and_update(f"已发送订单: {side} {lot_size} 合约，价格 {self.open_price}")

    async def send_order(self, side, pos_side, size):
        order_message = {
            "op": "order",
            "args": [{
                "instId": "BTC-USDT-SWAP",
                "tdMode": "cross",
                "side": side,
                "ordType": "market",
                "sz": str(size),
                "posSide": pos_side,
            }]
        }
        await self.websocket.send(json.dumps(order_message))

    def manage_open_positions(self):
        for position in self.open_positions:
            pos_type = position['posSide']
            entry_price = float(position['avgPx'])
            current_price = self.current_price

            if pos_type == 'long':
                dynamic_stop_loss = max(self.open_price - ATR_MULTIPLIER * self.atr, self.ma_values[2])
                take_profit = current_price + TAKE_PROFIT * self.atr

                if current_price < dynamic_stop_loss:
                    asyncio.create_task(self.close_position(position))
                    self.log_and_update(f"多头仓位平仓（止损）。入场: {entry_price}, 出场: {current_price}")
                else:
                    asyncio.create_task(self.modify_position(position, dynamic_stop_loss, take_profit))

            elif pos_type == 'short':
                dynamic_stop_loss = min(self.open_price + ATR_MULTIPLIER * self.atr, self.ma_values[2])
                take_profit = current_price - TAKE_PROFIT * self.atr

                if current_price > dynamic_stop_loss:
                    asyncio.create_task(self.close_position(position))
                    self.log_and_update(f"空头仓位平仓（止损）。入场: {entry_price}, 出场: {current_price}")
                else:
                    asyncio.create_task(self.modify_position(position, dynamic_stop_loss, take_profit))

    async def close_position(self, position):
        close_message = {
            "op": "close-position",
            "args": [{
                "instId": "BTC-USDT-SWAP",
                "posSide": position['posSide'],
            }]
        }
        await self.websocket.send(json.dumps(close_message))
        self.log_and_update(f"已发送平仓指令: {position['posSide']} 仓位")

    async def modify_position(self, position, stop_loss, take_profit):
        modify_message = {
            "op": "amend-order",
            "args": [{
                "instId": "BTC-USDT-SWAP",
                "posSide": position['posSide'],
                "newSlTriggerPx": str(stop_loss),
                "newTpTriggerPx": str(take_profit)
            }]
        }
        await self.websocket.send(json.dumps(modify_message))
        self.log_and_update(
            f"已发送修改仓位指令: {position['posSide']} 仓位, 新止损: {stop_loss}, 新止盈: {take_profit}")

    async def run_strategy(self):
        max_retries = 5
        retry_delay = 5
        for attempt in range(max_retries):
            try:
                await self.initialize_websocket()
                self.log_and_update("策略开始运行...")
                while True:
                    if not self.paused:
                        try:
                            message = await asyncio.wait_for(self.websocket.recv(), timeout=30)
                            await self.handle_message(json.loads(message))
                        except asyncio.TimeoutError:
                            self.log_and_update("WebSocket接收超时，正在重新连接...", logging.WARNING)
                            break
                        except websockets.exceptions.ConnectionClosed:
                            self.log_and_update("WebSocket连接已关闭，正在重新连接...", logging.WARNING)
                            break
                        except Exception as e:
                            self.log_and_update(f"处理消息时出错: {str(e)}", logging.ERROR)
                            import traceback
                            traceback.print_exc()
                    else:
                        await asyncio.sleep(1)
            except Exception as e:
                self.log_and_update(f"策略运行出错: {str(e)}", logging.ERROR)
                import traceback
                traceback.print_exc()

            if attempt < max_retries - 1:
                self.log_and_update(f"{retry_delay}秒后重试... (尝试 {attempt + 1}/{max_retries})", logging.INFO)
                await asyncio.sleep(retry_delay)
            else:
                self.log_and_update("达到最大重试次数。策略停止。", logging.ERROR)
                break

        self.log_and_update("策略已停止。")

    def run(self):
        print("交易策略开始运行...")
        asyncio.run(self.run_strategy())

    def pause(self):
        self.paused = True
        self.log_and_update("策略已暂停")

    def resume(self):
        self.paused = False
        self.log_and_update("策略已恢复")

    def start(self):
        self.run()