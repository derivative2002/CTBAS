import datetime
import json
import sys
import time
import hmac
import hashlib
import base64
import traceback
import logging
import numpy as np
import asyncio
import websockets
from PyQt5.QtCore import QThread, pyqtSignal
from queue import Empty
from utils import get_timestamp
from config import api_key, secret_key, passphrase, TAKE_PROFIT, MA_PERIODS, ATR_PERIOD, ATR_MULTIPLIER, RISK_PERCENT, TREND_MA_PERIOD

class TradingStrategy(QThread):
    log_message_signal = pyqtSignal(str)
    update_balance_signal = pyqtSignal(str, float, float)
    update_position_info_signal = pyqtSignal(list)

    def __init__(self, data_queue, analysis_window):
        super().__init__()
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.data_queue = data_queue
        self.analysis_window = analysis_window
        self.paused = False
        self.websocket = None

        # 连接信号和槽
        self.log_message_signal.connect(analysis_window.add_message_signal)
        self.update_balance_signal.connect(analysis_window.update_balance_signal)
        self.update_position_info_signal.connect(analysis_window.update_position_info_signal)

        # 设置日志
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levellevel)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    async def initialize_websocket(self):
        uri = "wss://wspap.okx.com:8443/ws/v5/private?brokerId=9999"
        self.websocket = await websockets.connect(uri)
        subscribe_message = {
            "op": "subscribe",
            "args": [
                {"channel": "account", "ccy": "USDT"},
                {"channel": "positions", "instId": "BTC-USDT-SWAP"},
                {"channel": "orders", "instId": "BTC-USDT-SWAP"}
            ]
        }
        await self.websocket.send(json.dumps(subscribe_message))

    async def on_message(self, message):
        data = json.loads(message)
        if 'arg' in data:
            channel = data['arg']['channel']
            if channel == 'account':
                self.handle_account_message(data)
            elif channel == 'positions':
                self.handle_positions_message(data)
            elif channel == 'orders':
                self.handle_orders_message(data)

    def handle_account_message(self, message):
        if 'data' in message:
            balance_info = message['data'][0]
            self.account_balance = float(balance_info['details'][0]['cashBal'])
            self.update_balance()

    def handle_positions_message(self, message):
        if 'data' in message:
            self.open_positions = message['data']
            self.update_positions()

    def handle_orders_message(self, message):
        if 'data' in message:
            order_info = message['data'][0]
            self.log_and_update(f"订单更新: {order_info}")

    async def send_order(self, side, pos_side, size):
        order_message = {
            "op": "order",
            "args": [{
                "instId": "BTC-USDT-SWAP",
                "tdMode": "cross",
                "side": side,
                "ordType": "market",
                "sz": f"{size:.4f}",
                "posSide": pos_side,
            }]
        }
        await self.websocket.send(json.dumps(order_message))

    def initialize_strategy(self):
        self.open_positions = []
        self.strategy_status = "空闲"
        self.account_balance = None
        self.ma_values = np.zeros(len(MA_PERIODS))
        self.prev_ma_values = np.zeros(len(MA_PERIODS))
        self.trend_ma = 0
        self.atr = 0

    def log_and_update(self, message, level=logging.INFO):
        """统一的日志记录和UI更新方法"""
        self.logger.log(level, message)
        self.log_message_signal.emit(message)

    def get_current_price(self):
        endpoint = "/api/v5/market/ticker?instId=BTC-USDT-SWAP"
        response = self.get_data_with_retry(endpoint)
        if response and 'data' in response:
            return float(response['data'][0]['last'])
        return None

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
                self.log_and_update(f"请求失败 (尝试 {attempt + 1}/{max_retries}): {e}", logging.ERROR)
                self.log_and_update(f"请求详情: URL={url}, 方法={method}, 参数={params}, 数据={data}", logging.DEBUG)
                if attempt < max_retries - 1:
                    time.sleep(delay)
        self.log_and_update("所有重试都失败了", logging.ERROR)
        return None

    def get_open_positions_value(self):
        floating_profit = 0

        for position in self.open_positions:
            current_price = self.get_current_price()
            if current_price is None:
                continue

            if position['type'] == "buy":
                profit = (current_price - position['open_price']) * position['size']
            else:  # sell
                profit = (position['open_price'] - current_price) * position['size']

            floating_profit += profit

        return 0, floating_profit

    def update_balance(self):
        self.account_balance = self.get_account_balance()
        positions_value, floating_profit = self.get_open_positions_value()
        total_value = self.account_balance + floating_profit

        self.update_balance_signal.emit(self.account_balance, floating_profit, total_value)

    def get_position_summary(self, position):
        if position is None:
            return "当前无持仓"

        current_price = self.get_current_price()
        if current_price is None:
            return "无法获取当前价格"

        if position['type'] == "buy":
            profit = (current_price - position['open_price']) * position['size']
            profit_percentage = (current_price - position['open_price']) / position['open_price'] * 100
        else:  # sell
            profit = (position['open_price'] - current_price) * position['size']
            profit_percentage = (position['open_price'] - current_price) / position['open_price'] * 100

        return (
            f"持仓方向: {position['type'].upper()}\n"
            f"持仓量: {position['size']} BTC\n"
            f"开仓价: {position['open_price']:.2f}\n"
            f"当前价格: {current_price:.2f}\n"
            f"当前收益: {profit:.2f} USDT ({profit_percentage:.2f}%)\n"
            f"止损价: {position['stop_loss_price']:.2f}\n"
            f"止盈价: {position['take_profit_price']:.2f}"
        )

    def get_kline_data(self):
        endpoint = "/api/v5/market/candles"
        params = {
            'instId': 'BTC-USDT-SWAP',
            'bar': '1m',
            'limit': str(max(max(MA_PERIODS), TREND_MA_PERIOD, ATR_PERIOD + 1))
        }
        response = self.get_data_with_retry(endpoint, params=params)

        if response and 'data' in response:
            data = response['data']
            if len(data) > 0:
                self.log_and_update(f"成功获取 {len(data)} 条K线数据")
                return data
            else:
                self.log_and_update("获取的K线数据为空", logging.ERROR)
        self.log_and_update("获取K线数据失败", logging.ERROR)
        return []

    def update_indicators(self, kline_data):
        if len(kline_data) < max(max(MA_PERIODS), TREND_MA_PERIOD, ATR_PERIOD + 1):
            self.log_and_update(f"K线数据不足，当前数据量: {len(kline_data)}", logging.WARNING)
            return

        close_prices = np.array([float(k[4]) for k in kline_data])[::-1]
        high_prices = np.array([float(k[2]) for k in kline_data])[::-1]
        low_prices = np.array([float(k[3]) for k in kline_data])[::-1]

        # 计算MA
        for i, period in enumerate(MA_PERIODS):
            self.prev_ma_values[i] = self.ma_values[i]
            self.ma_values[i] = np.mean(close_prices[:period])

        # 计算趋势MA
        self.trend_ma = np.mean(close_prices[:TREND_MA_PERIOD])

        # 计算ATR
        self.atr = self.calculate_atr(high_prices, low_prices, close_prices, ATR_PERIOD)

        if np.isnan(self.atr) or self.atr == 0:
            self.log_and_update("ATR 计算结果无效", logging.WARNING)
            self.atr = None

        self.log_and_update("指标更新完成")
        self.log_and_update(f"MA values: {self.ma_values}")
        self.log_and_update(f"Trend MA: {self.trend_ma}")
        self.log_and_update(f"ATR: {self.atr}")

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

    def check_buy_condition(self, current_price):
        if np.isnan(self.trend_ma) or current_price <= self.trend_ma:
            return False, ["价格未突破趋势MA"]

        for ma_value in self.ma_values:
            if np.isnan(ma_value) or current_price <= ma_value:
                return False, ["价格未突破所有MA"]

        if self.prev_ma_values[2] is not None and self.get_previous_close_price() > self.prev_ma_values[2]:
            return False, ["上一根K线的收盘价未低于30日移动平均线"]

        return True, ["所有做多条件满足"]

    def check_sell_condition(self, current_price):
        if np.isnan(self.trend_ma) or current_price >= self.trend_ma:
            return False, ["价格未跌破趋势MA"]

        for ma_value in self.ma_values:
            if np.isnan(ma_value) or current_price >= ma_value:
                return False, ["价格未跌破所有MA"]

        if self.prev_ma_values[2] is not None and self.get_previous_close_price() < self.prev_ma_values[2]:
            return False, ["上一根K线的收盘价未高于30日移动平均线"]

        return True, ["所有做空条件满足"]

    def get_previous_close_price(self):
        endpoint = "/api/v5/market/ticker?instId=BTC-USDT-SWAP"
        response = self.get_data_with_retry(endpoint)
        if response and 'data' in response:
            return float(response['data'][0]['last'])
        return None

    def calculate_lot_size(self, account_balance, atr):
        if atr is None or atr == 0:
            self.log_and_update("ATR 为 0，无法计算交易量", logging.WARNING)
            return None

        risk_amount = account_balance * RISK_PERCENT / 100.0
        stop_loss_distance = ATR_MULTIPLIER * atr

        current_price = self.get_current_price()
        if current_price is None:
            self.log_and_update("无法获取当前价格，无法计算交易量", logging.WARNING)
            return None

        symbol_info = self.get_symbol_info("BTC-USDT-SWAP")
        if symbol_info is None:
            self.log_and_update("无法获取完整的交易品种信息，使用默认值", logging.WARNING)
            return None

        tick_size = symbol_info['tick_size']
        tick_value = symbol_info['tick_value']

        risk_per_lot = stop_loss_distance / tick_size * tick_value
        lot_size = risk_amount / risk_per_lot

        self.log_and_update(f"计算的交易量: {lot_size:.4f} 手")

        return lot_size

    def get_symbol_info(self, symbol):
        endpoint = f"/api/v5/public/instruments"
        params = {
            'instType': 'SWAP',
            'instId': symbol
        }
        response = self.get_data_with_retry(endpoint, params=params)
        if response and 'data' in response:
            if len(response['data']) > 0:
                instrument_info = response['data'][0]
                return {
                    'tick_size': float(instrument_info.get('tickSz', '0.1')),
                    'min_size': float(instrument_info.get('minSz', '0.1')),
                    'max_size': float(instrument_info.get('maxSz', '100.0')),
                    'step_size': float(instrument_info.get('lotSz', '0.1')),
                    'tick_value': float(instrument_info.get('tickVal', '1')),
                    'contract_val': float(instrument_info.get('ctVal', '0.001')),
                    'contract_multiplier': float(instrument_info.get('ctMult', '1')),
                    'max_leverage': float(instrument_info.get('lever', '100')),
                    'contract_size': float(instrument_info.get('ctVal', '100')),
                }
            else:
                self.log_and_update("获取的交易品种数据为空", logging.WARNING)
        else:
            self.log_and_update(f"无法获取交易品种信息，错误信息: {response.get('msg', '未知错误')}", logging.ERROR)
        return None

    def open_position(self, order_type):
        if self.account_balance is None:
            self.update_balance()
        if self.account_balance is None or self.account_balance <= 0:
            self.log_and_update("账户余额不足，无法开仓", logging.WARNING)
            return None

        lot_size = self.calculate_lot_size(self.account_balance, self.atr)
        if lot_size is None:
            return None

        side = "buy" if order_type == "buy" else "sell"
        pos_side = "long" if order_type == "buy" else "short"
        current_price = self.get_current_price()
        if current_price is None:
            self.log_and_update("无法获取当前价格，开仓失败", logging.WARNING)
            return None

        symbol_info = self.get_symbol_info("BTC-USDT-SWAP")
        if symbol_info is None:
            self.log_and_update("无法获取交易品种信息，开仓失败", logging.ERROR)
            return None

        contract_size = symbol_info['contract_val']
        num_contracts = lot_size / contract_size

        min_size = symbol_info['min_size']
        adjusted_num_contracts = max(round(num_contracts / min_size) * min_size, min_size)

        if adjusted_num_contracts < min_size:
            self.log_and_update(f"计算的交易量 ({adjusted_num_contracts:.4f} 张) 过小，无法开仓", logging.WARNING)
            return None

        asyncio.run(self.send_order(side, pos_side, adjusted_num_contracts))
        self.log_and_update(f"已发送订单: {side} {adjusted_num_contracts} 手")

    def run(self):
        asyncio.run(self.run_strategy())

    async def run_strategy(self):
        await self.initialize_websocket()
        async for message in self.websocket:
            await self.on_message(message)
