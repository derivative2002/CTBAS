import datetime
import json
import time
import hmac
import hashlib
import base64
import traceback
import requests
import logging
import numpy as np
from requests.exceptions import RequestException
from utils import get_timestamp
from config import api_key, secret_key, passphrase, base_url, TAKE_PROFIT, MA_PERIODS, ATR_PERIOD, ATR_MULTIPLIER, \
    RISK_PERCENT, TREND_MA_PERIOD
from queue import Empty


def calculate_atr(high_prices, low_prices, close_prices, period):
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


class TradingStrategy:
    def __init__(self, data_queue, analysis_window):
        self.atr = None
        self.trend_ma = None
        self.prev_ma_values = None
        self.ma_values = None
        self.account_balance = None
        self.strategy_status = None
        self.open_positions = None
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.base_url = base_url
        self.data_queue = data_queue
        self.analysis_window = analysis_window
        self.session = requests.Session()
        self.initialize_strategy()
        self.paused = False

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

    def log_and_update(self, message, level=logging.INFO):
        """统一的日志记录和UI更新方法"""
        self.logger.log(level, message)
        self.analysis_window.add_message(message)

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
                self.log_and_update(f"请求失败 (尝试 {attempt + 1}/{max_retries}): {e}", logging.ERROR)
                self.log_and_update(f"请求详情: URL={url}, 方法={method}, 参数={params}, 数据={data}", logging.DEBUG)
                if attempt < max_retries - 1:
                    time.sleep(delay)
        self.log_and_update("所有重试都失败了", logging.ERROR)
        return None

    def get_account_balance(self):
        endpoint = "/api/v5/account/balance?ccy=USDT"
        response = self.get_data_with_retry(endpoint)
        if response and 'data' in response:
            return float(response['data'][0]['details'][0]['cashBal'])
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

        self.analysis_window.update_balance(self.account_balance, floating_profit, total_value)

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
        self.atr = calculate_atr(high_prices, low_prices, close_prices, ATR_PERIOD)

        if np.isnan(self.atr) or self.atr == 0:
            self.log_and_update("ATR 计算结果无效", logging.WARNING)
            self.atr = None

        self.log_and_update("指标更新完成")
        self.log_and_update(f"MA values: {self.ma_values}")
        self.log_and_update(f"Trend MA: {self.trend_ma}")
        self.log_and_update(f"ATR: {self.atr}")

    def check_buy_condition(self, current_price):
        if np.isnan(self.trend_ma) or current_price <= self.trend_ma:
            return False, ["价格未突破趋势MA"]

        for ma_value in self.ma_values:
            if np.isnan(ma_value) or current_price <= ma_value:
                return False, ["价格未突破所有MA"]

        # 检查上一根K线的收盘价是否低于30日移动平均线(MA_PERIOD3)
        if self.prev_ma_values[2] is not None and self.get_previous_close_price() > self.prev_ma_values[2]:
            return False, ["上一根K线的收盘价未低于30日移动平均线"]

        return True, ["所有做多条件满足"]

    def check_sell_condition(self, current_price):
        if np.isnan(self.trend_ma) or current_price >= self.trend_ma:
            return False, ["价格未跌破趋势MA"]

        for ma_value in self.ma_values:
            if np.isnan(ma_value) or current_price >= ma_value:
                return False, ["价格未跌破所有MA"]

        # 检查上一根K线的收盘价是否高于30日移动平均线(MA_PERIOD3)
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

        order_result = self.place_order(side, pos_side, adjusted_num_contracts)
        self.log_and_update(f"下单结果: {order_result}")

        if order_result and isinstance(order_result, list) and len(order_result) > 0:
            order_info = order_result[0]
            if order_info.get('sCode') == '0':
                order_id = order_info.get('ordId')
                if order_id:
                    order_status = self.check_order_status(order_id)

                    if order_status == 'filled':
                        position = {
                            'type': order_type,
                            'open_price': float(order_info.get('avgPx', current_price)),
                            'size': lot_size,
                            'open_time': time.time(),
                        }
                        self.open_positions.append(position)

                        self.log_and_update(
                            f"开仓成功: {order_type.capitalize()}单已成交, 手数={lot_size:.4f} (合约张数: {adjusted_num_contracts:.4f}), 开仓价={position['open_price']:.2f}")

                        self.update_balance()
                        return {'ordId': order_id}
                    elif order_status == 'pending':
                        self.log_and_update(f"下单已提交，但尚未完全成交。订单ID: {order_id}")
                        return {'ordId': order_id}
                    else:
                        self.log_and_update(f"下单状态未知。订单ID: {order_id}, 状态: {order_status}", logging.WARNING)
                else:
                    self.log_and_update(f"下单成功，但未能获取订单ID。订单信息: {order_info}", logging.WARNING)
            else:
                self.log_and_update(f"下单失败: {order_info.get('sMsg')}", logging.WARNING)
        else:
            self.log_and_update(f"{order_type.capitalize()}单下单失败。返回结果: {order_result}", logging.WARNING)

        return None
    def check_order_status(self, order_id, max_retries=5):
        for _ in range(max_retries):
            order_info = self.get_order_info(order_id)
            if order_info and len(order_info) > 0:
                state = order_info[0].get('state', 'unknown')
                if state in ['live', 'partially_filled']:
                    return 'pending'
                elif state == 'filled':
                    return 'filled'
                elif state in ['canceled', 'order_failed']:
                    return 'failed'
            elif order_info is None:
                time.sleep(1)
                continue
            time.sleep(1)
        return 'unknown'

    def place_order(self, side, pos_side, size):
        endpoint = "/api/v5/trade/order"
        order_data = {
            "instId": "BTC-USDT-SWAP",
            "tdMode": "cross",
            "side": side,
            "ordType": "market",
            "sz": f"{size:.4f}",
            "posSide": pos_side,
        }

        response = self.get_data_with_retry(endpoint, method="POST", data=order_data)
        self.log_and_update(f"下单API请求: {order_data}")
        self.log_and_update(f"下单API响应: {response}")

        if response and 'data' in response:
            return response['data']
        return None

    def get_order_info(self, order_id):
        endpoint = f"/api/v5/trade/order?instId=BTC-USDT-SWAP&ordId={order_id}"
        response = self.get_data_with_retry(endpoint, method="GET")
        if response and 'data' in response:
            return response['data']
        elif 'code' in response and 'msg' in response:
            self.log_and_update(f"获取订单信息失败: {response['msg']} (错误码: {response['code']})", logging.ERROR)
        return None

    def close_position(self, position):
        if not self.open_positions:
            self.log_and_update("没有持仓可以平仓", logging.WARNING)
            return False

        current_price = self.get_current_price()
        if current_price is None:
            self.log_and_update("无法获取当前价格，平仓失败", logging.WARNING)
            return False

        side = "sell" if position['type'] == "buy" else "buy"
        pos_side = "long" if position['type'] == "buy" else "short"

        symbol_info = self.get_symbol_info("BTC-USDT-SWAP")
        if symbol_info is None:
            self.log_and_update("无法获取交易品种信息，平仓失败", logging.ERROR)
            return False

        contract_val = symbol_info['contract_val']
        num_contracts = position['size'] / contract_val
        min_size = symbol_info['min_size']
        adjusted_num_contracts = max(round(num_contracts / min_size) * min_size, min_size)

        order_result = self.place_order(side, pos_side, adjusted_num_contracts)
        self.log_and_update(f"平仓下单结果: {order_result}")

        if order_result and isinstance(order_result, list) and len(order_result) > 0:
            order_info = order_result[0]
            if order_info.get('sCode') == '0':
                order_id = order_info.get('ordId')
                if order_id:
                    order_status = self.check_order_status(order_id)

                    if order_status == 'filled':
                        close_price = float(order_info.get('avgPx', current_price))
                        profit = (close_price - position['open_price']) * position['size'] if position[
                                                                                                  'type'] == "buy" else (
                                                                                                                                position[
                                                                                                                                    'open_price'] - close_price) * \
                                                                                                                        position[
                                                                                                                            'size']
                        self.log_and_update(
                            f"平仓成功: 开仓价={position['open_price']:.2f}, 平仓价={close_price:.2f}, "
                            f"数量={position['size']:.4f} BTC (合约张数: {adjusted_num_contracts:.4f}), 盈亏={profit:.2f} USDT")
                        self.open_positions.remove(position)
                        self.update_balance()
                        return True
                    elif order_status == 'pending':
                        self.log_and_update(f"平仓订单已提交，但尚未完全成交。订单ID: {order_id}")
                        return False
                    else:
                        self.log_and_update(f"平仓订单状态未知。订单ID: {order_id}, 状态: {order_status}",
                                            logging.WARNING)
                        return False
                else:
                    self.log_and_update(f"平仓下单成功，但未能获取订单ID。订单信息: {order_info}", logging.WARNING)
                    return False
            else:
                self.log_and_update(f"平仓下单失败: {order_info.get('sMsg')}", logging.WARNING)
                return False
        else:
            self.log_and_update(f"平仓下单失败。返回结果: {order_result}", logging.WARNING)
            return False

    def get_current_price(self):
        endpoint = "/api/v5/market/ticker?instId=BTC-USDT-SWAP"
        response = self.get_data_with_retry(endpoint)
        if response and 'data' in response:
            return float(response['data'][0]['last'])
        return None

    def manage_open_positions(self, current_price):
        for position in self.open_positions:
            if position is None or position['open_time'] is None:
                continue

            if (time.time() - position['open_time']) < 5:
                continue

            if position['type'] == "buy":
                profit = (current_price - position['open_price']) * position['size']
                profit_percentage = (current_price - position['open_price']) / position['open_price'] * 100
                new_stop_loss = max(position['open_price'] - ATR_MULTIPLIER * self.atr, self.ma_values[2])
                new_take_profit = min(position['open_price'] + TAKE_PROFIT * self.atr, current_price)
                should_close = current_price <= new_stop_loss * 0.99 or current_price >= new_take_profit * 1.01
            elif position['type'] == "sell":
                profit = (position['open_price'] - current_price) * position['size']
                profit_percentage = (position['open_price'] - current_price) / position['open_price'] * 100
                new_stop_loss = min(position['open_price'] + ATR_MULTIPLIER * self.atr, self.ma_values[2])
                new_take_profit = max(position['open_price'] - TAKE_PROFIT * self.atr, current_price)
                should_close = current_price >= new_stop_loss * 1.01 or current_price <= new_take_profit * 0.99
            else:
                self.log_and_update("错误：无效的持仓方向", logging.ERROR)
                continue

            if should_close:
                close_reason = '止损' if (position['type'] == "buy" and current_price <= new_stop_loss * 0.99) or (
                        position['type'] == "sell" and current_price >= new_stop_loss * 1.01) else '止盈'
                self.log_and_update(
                    f"触发{close_reason}: 当前价格={current_price:.2f}, 目标价={new_stop_loss:.2f if close_reason == '止损' else new_take_profit:.2f}")
                self.close_position(position)
            else:
                position['stop_loss_price'] = new_stop_loss
                position['take_profit_price'] = new_take_profit

                self.log_and_update(
                    f"持仓管理: 当前价格={current_price:.2f}, 开仓价={position['open_price']:.2f}, "
                    f"当前止损价={position['stop_loss_price']:.2f}, 当前止盈价={position['take_profit_price']:.2f}\n"
                    f"持仓方向: {position['type'].upper()}, 持仓量: {position['size']} BTC\n"
                    f"当前收益: {profit:.2f} USDT ({profit_percentage:.2f}%)"
                )

        if not self.open_positions:
            self.log_and_update("所有持仓已平仓")
    def pause(self):
        self.paused = True
        self.log_and_update("交易策略已暂停")

    def resume(self):
        self.paused = False
        self.log_and_update("交易策略已恢复")

    def run(self):
        self.log_and_update("交易策略开始运行...")
        self.account_balance = self.get_account_balance()
        if self.account_balance is None:
            self.log_and_update("无法获取账户余额，策略停止运行", logging.ERROR)
            return

        last_kline_update = 0
        kline_update_interval = 1  # 每1秒更新一次K线数据
        timestamps = []
        prices = []

        trade_count = 0
        last_check_time = datetime.datetime.now()
        pending_orders = {}

        while True:
            if self.paused:
                time.sleep(1)
                continue

            try:
                current_time = datetime.datetime.now()
                time_diff = current_time - last_check_time

                if time_diff.total_seconds() >= 1800:
                    if trade_count == 0:
                        self.log_and_update("警告：过去30分钟内没有交易发生", logging.WARNING)
                    elif trade_count < 3:
                        self.log_and_update(f"警告：过去30分钟内交易次数较少，仅有 {trade_count} 次", logging.WARNING)
                    else:
                        self.log_and_update(f"过去30分钟内交易次数：{trade_count}")

                    trade_count = 0
                    last_check_time = current_time

                for order_id, order_time in list(pending_orders.items()):
                    if time.time() - order_time > 300:
                        order_status = self.check_order_status(order_id)
                        if order_status == 'filled':
                            self.log_and_update(f"订单 {order_id} 已成交")
                            del pending_orders[order_id]
                            trade_count += 1
                        elif order_status == 'failed':
                            self.log_and_update(f"订单 {order_id} 已失败", logging.WARNING)
                            del pending_orders[order_id]
                        elif order_status == 'pending':
                            self.log_and_update(f"订单 {order_id} 仍在等待成交")
                        else:
                            self.log_and_update(f"订单 {order_id} 状态未知，考虑手动检查", logging.WARNING)
                            del pending_orders[order_id]

                item = self.data_queue.get(timeout=5)
                if 'last' in item:
                    current_price = float(item['last'])
                    current_time = time.time()
                    self.log_and_update(f"当前价格: {current_price}")

                    timestamps.append(datetime.datetime.now())
                    prices.append(current_price)
                    if len(timestamps) > 100:
                        timestamps.pop(0)
                        prices.pop(0)
                    self.analysis_window.update_chart({'timestamps': timestamps, 'prices': prices})

                    if current_time - last_kline_update >= kline_update_interval:
                        kline_data = self.get_kline_data()
                        if kline_data:
                            self.update_indicators(kline_data)
                            last_kline_update = current_time
                            self.log_and_update(f"K线数据已更新，共{len(kline_data)}条数据")
                            self.log_and_update(
                                f"当前指标: MA值={self.ma_values}, 趋势MA={self.trend_ma}, ATR={self.atr}")
                        else:
                            self.log_and_update("无法获取K线数据", logging.WARNING)

                    buy_condition, buy_reasons = self.check_buy_condition(current_price)
                    sell_condition, sell_reasons = self.check_sell_condition(current_price)

                    self.log_and_update("策略分析:")
                    self.log_and_update(f"做多条件满足: {buy_condition}")
                    for reason in buy_reasons:
                        self.log_and_update(f"  - {reason}")
                    self.log_and_update(f"做空条件满足: {sell_condition}")
                    for reason in sell_reasons:
                        self.log_and_update(f"  - {reason}")

                if self.account_balance is None:
                    self.update_balance()

                if buy_condition and self.atr is not None and self.atr > 0:
                    order_result = self.open_position("buy")
                    if isinstance(order_result, dict) and 'ordId' in order_result:
                        pending_orders[order_result['ordId']] = time.time()
                    else:
                        self.log_and_update(f"开仓失败或返回异常结果: {order_result}", logging.WARNING)
                elif sell_condition and self.atr is not None and self.atr > 0:
                    order_result = self.open_position("sell")
                    if isinstance(order_result, dict) and 'ordId' in order_result:
                        pending_orders[order_result['ordId']] = time.time()
                    else:
                        self.log_and_update(f"开仓失败或返回异常结果: {order_result}", logging.WARNING)

                if self.open_positions:
                    self.manage_open_positions(current_price)

            except Empty:
                self.log_and_update("等待数据...", logging.DEBUG)
                continue
            except Exception as e:
                self.log_and_update(f"发生错误: {str(e)}", logging.ERROR)
                self.log_and_update(f"错误详情: {traceback.format_exc()}", logging.DEBUG)
                time.sleep(5)

        self.log_and_update("交易策略运行结束")
        self.log_and_update(f"最终账户余额: {self.get_account_balance()} USDT")
