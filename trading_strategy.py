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

class TradingStrategy:
    def __init__(self, data_queue, analysis_window):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.base_url = base_url
        self.data_queue = data_queue
        self.analysis_window = analysis_window
        self.session = requests.Session()
        self.initialize_strategy()
        self.paused = False

    def initialize_strategy(self):
        self.open_positions = []
        self.strategy_status = "空闲"
        self.account_balance = None
        self.ma_values = np.zeros(len(MA_PERIODS))
        self.prev_ma_values = np.zeros(len(MA_PERIODS))
        self.trend_ma = 0
        self.atr = 0

    def update_analysis_window(self, message):
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
                logging.error(f"请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(delay)
        logging.error("所有重试都失败了")
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
                logging.info(f"成功获取 {len(data)} 条K线数据")
                return data
            else:
                logging.error("获取的K线数据为空")
        logging.error("获取K线数据失败")
        return []

    def update_indicators(self, kline_data):
        if len(kline_data) < max(max(MA_PERIODS), TREND_MA_PERIOD, ATR_PERIOD + 1):
            logging.warning(f"K线数据不足，当前数据量: {len(kline_data)}")
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
            logging.warning("ATR 计算结果无效")
            self.atr = None

        logging.info("指标更新完成")
        logging.info(f"MA values: {self.ma_values}")
        logging.info(f"Trend MA: {self.trend_ma}")
        logging.info(f"ATR: {self.atr}")

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

        return True, ["所有做多条件满足"]

    def check_sell_condition(self, current_price):
        if np.isnan(self.trend_ma) or current_price >= self.trend_ma:
            return False, ["价格未跌破趋势MA"]

        for ma_value in self.ma_values:
            if np.isnan(ma_value) or current_price >= ma_value:
                return False, ["价格未跌破所有MA"]

        return True, ["所有做空条件满足"]

    def calculate_lot_size(self, account_balance, atr):
        if atr is None or atr == 0:
            self.update_analysis_window("ATR 为 0，无法计算交易量")
            return None

        risk_amount = account_balance * RISK_PERCENT / 100.0
        stop_loss_distance = ATR_MULTIPLIER * atr

        current_price = self.get_current_price()
        if current_price is None:
            self.update_analysis_window("无法获取当前价格，无法计算交易量")
            return None

        symbol_info = self.get_symbol_info("BTC-USDT-SWAP")
        if symbol_info is None:
            self.update_analysis_window("无法获取完整的交易品种信息，使用默认值")
            return None

        min_lot_size = symbol_info['min_size']
        max_lot_size = symbol_info['max_size']
        step_lot_size = symbol_info['step_size']
        tick_size = symbol_info['tick_size']
        tick_value = symbol_info['tick_value']
        contract_val = symbol_info['contract_val']  # 合约面值

        risk_per_unit = stop_loss_distance / tick_size * tick_value
        lot_size = risk_amount / risk_per_unit

        # 确保交易量不低于最小交易量并且是tick_size的整数倍
        lot_size = max(min(lot_size, max_lot_size), min_lot_size)
        lot_size = round(lot_size / step_lot_size) * step_lot_size

        # 计算张数
        num_contracts = lot_size / contract_val

        self.update_analysis_window(
            f"计算的交易量: {lot_size:.4f} 手 (相当于 {num_contracts:.4f} 张， {lot_size:.4f} BTC)")

        return lot_size, num_contracts

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
                    'max_size': float(instrument_info.get('maxSz', '100.0')),  # 添加默认值
                    'step_size': float(instrument_info.get('lotSz', '0.1')),  # 添加默认值
                    'tick_value': float(instrument_info.get('tickVal', '1')),  # 添加默认值
                    'contract_val': float(instrument_info.get('ctVal', '0.001')),
                    'contract_multiplier': float(instrument_info.get('ctMult', '1')),
                    'max_leverage': float(instrument_info.get('lever', '100')),
                    'contract_size': float(instrument_info.get('ctVal', '100')),
                }
            else:
                self.update_analysis_window("获取的交易品种数据为空")
        else:
            self.update_analysis_window(f"无法获取交易品种信息，错误信息: {response.get('msg', '未知错误')}")

        return None

    def open_position(self, order_type):
        lot_size, num_contracts = self.calculate_lot_size(self.account_balance, self.atr)
        if lot_size is None or lot_size < 0.001:
            self.update_analysis_window("计算的交易量过小，无法开仓")
            return None

        side = "buy" if order_type == "buy" else "sell"
        pos_side = "long" if order_type == "buy" else "short"

        current_price = self.get_current_price()
        if current_price is None:
            self.update_analysis_window("无法获取当前价格，开仓失败")
            return None

        order_result = self.place_order(side, pos_side, current_price, num_contracts)
        self.update_analysis_window(f"下单结果: {order_result}")

        if order_result and isinstance(order_result, list) and len(order_result) > 0:
            order_info = order_result[0]
            order_id = order_info.get('ordId')
            if order_id:
                order_status = self.check_order_status(order_id)

                if order_status == 'filled':
                    position = {
                        'type': order_type,
                        'open_price': float(order_info.get('avgPx', current_price)),
                        'size': lot_size,
                        'open_time': time.time(),
                        'stop_loss_price': 0,
                        'take_profit_price': 0,
                    }
                    if order_type == "buy":
                        position['stop_loss_price'] = position['open_price'] - ATR_MULTIPLIER * self.atr
                        position['take_profit_price'] = position['open_price'] + TAKE_PROFIT * self.atr
                    else:
                        position['stop_loss_price'] = position['open_price'] + ATR_MULTIPLIER * self.atr
                        position['take_profit_price'] = position['open_price'] - TAKE_PROFIT * self.atr

                    self.open_positions.append(position)

                    self.update_analysis_window(
                        f"下单成功: {order_type.capitalize()}单已成交: 数量={num_contracts:.4f} 张 (相当于 {lot_size:.4f} BTC), 开仓价={position['open_price']:.2f}, "
                        f"初始止损价={position['stop_loss_price']:.2f}, 初始止盈价={position['take_profit_price']:.2f}")
                    self.update_balance()
                    return {'ordId': order_id}
                elif order_status == 'pending':
                    self.update_analysis_window(f"下单已提交，但尚未完全成交。订单ID: {order_id}")
                    return {'ordId': order_id}
                else:
                    self.update_analysis_window(f"下单状态未知。订单ID: {order_id}, 状态: {order_status}")
            else:
                self.update_analysis_window(f"下单成功，但未能获取订单ID。订单信息: {order_info}")
        else:
            self.update_analysis_window(f"{order_type.capitalize()}单下单失败。返回结果: {order_result}")

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

    def place_order(self, side, pos_side, price, size=None):
        endpoint = "/api/v5/trade/order"
        order_data = {
            "instId": "BTC-USDT-SWAP",
            "tdMode": "cross",
            "side": side,
            "ordType": "market",
            "px": str(price),
            "sz": f"{size:.1f}",
            "posSide": pos_side,
        }

        response = self.get_data_with_retry(endpoint, method="POST", data=order_data)
        self.update_analysis_window(f"下单API响应: {response}")

        if response and 'data' in response:
            return response['data']
        return None

    def get_order_info(self, order_id):
        endpoint = f"/api/v5/trade/order?instId=BTC-USDT-SWAP&ordId={order_id}"
        response = self.get_data_with_retry(endpoint, method="GET")
        if response and 'data' in response:
            return response['data']
        elif 'code' in response and 'msg' in response:
            self.update_analysis_window(f"获取订单信息失败: {response['msg']} (错误码: {response['code']})")
        return None

    def close_position(self, position):
        current_price = self.get_current_price()
        if current_price is None:
            self.update_analysis_window("无法获取当前价格，平仓失败")
            return

        side = "sell" if position['type'] == "buy" else "buy"
        pos_side = "long" if position['type'] == "buy" else "short"

        order_result = self.place_order(side, pos_side, current_price, position['size'])
        if order_result:
            order_info = self.get_order_info(order_result[0].get('ordId'))
            if order_info:
                close_price = float(order_info[0].get('avgPx', current_price))
                profit = (close_price - position['open_price']) * position['size'] if position['type'] == "buy" else (
                                                                                     position['open_price'] - close_price) * position['size']
                self.update_analysis_window(
                    f"平仓成功: 开仓价={position['open_price']}, 平仓价={close_price}, 数量={position['size']} BTC, 盈亏={profit:.2f} USDT")
                self.open_positions.remove(position)
                self.update_balance()
            else:
                self.update_analysis_window("获取订单信息失败")
        else:
            self.update_analysis_window("平仓失败")

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
                new_stop_loss = max(position['stop_loss_price'], position['open_price'] - ATR_MULTIPLIER * self.atr)
                new_take_profit = max(position['take_profit_price'], position['open_price'] + TAKE_PROFIT * self.atr)
            elif position['type'] == "sell":
                profit = (position['open_price'] - current_price) * position['size']
                profit_percentage = (position['open_price'] - current_price) / position['open_price'] * 100
                new_stop_loss = min(position['stop_loss_price'], position['open_price'] + ATR_MULTIPLIER * self.atr)
                new_take_profit = min(position['take_profit_price'], position['open_price'] - TAKE_PROFIT * self.atr)
            else:
                self.update_analysis_window("错误：无效的持仓方向")
                return

            if (position['type'] == "buy" and current_price <= new_stop_loss) or \
                    (position['type'] == "sell" and current_price >= new_stop_loss):
                self.update_analysis_window(f"触发止损: 当前价格={current_price:.2f}, 止损价={new_stop_loss:.2f}")
                self.close_position(position)
            elif (position['type'] == "buy" and current_price >= new_take_profit) or \
                    (position['type'] == "sell" and current_price <= new_take_profit):
                self.update_analysis_window(f"触发止盈: 当前价格={current_price:.2f}, 止盈价={new_take_profit:.2f}")
                self.close_position(position)
            else:
                position['stop_loss_price'] = new_stop_loss
                position['take_profit_price'] = new_take_profit

                self.update_analysis_window(
                    f"持仓管理: 当前价格={current_price:.2f}, 开仓价={position['open_price']:.2f}, "
                    f"当前止损价={position['stop_loss_price']:.2f}, 当前止盈价={position['take_profit_price']:.2f}\n"
                    f"持仓方向: {position['type'].upper()}, 持仓量: {position['size']} BTC\n"
                    f"当前收益: {profit:.2f} USDT ({profit_percentage:.2f}%)"
                )

        if not self.open_positions:
            self.update_analysis_window("所有持仓已平仓")

    def pause(self):
        self.paused = True
        self.update_analysis_window("交易策略已暂停")

    def resume(self):
        self.paused = False
        self.update_analysis_window("交易策略已恢复")

    def run(self):
        self.update_analysis_window("交易策略开始运行...")
        self.account_balance = self.get_account_balance()
        if self.account_balance is None:
            self.update_analysis_window("无法获取账户余额，策略停止运行")
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
                        self.update_analysis_window("警告：过去30分钟内没有交易发生")
                    elif trade_count < 3:
                        self.update_analysis_window(f"警告：过去30分钟内交易次数较少，仅有 {trade_count} 次")
                    else:
                        self.update_analysis_window(f"过去30分钟内交易次数：{trade_count}")

                    trade_count = 0
                    last_check_time = current_time

                for order_id, order_time in list(pending_orders.items()):
                    if time.time() - order_time > 300:
                        order_status = self.check_order_status(order_id)
                        if order_status == 'filled':
                            self.update_analysis_window(f"订单 {order_id} 已成交")
                            del pending_orders[order_id]
                            trade_count += 1
                        elif order_status == 'failed':
                            self.update_analysis_window(f"订单 {order_id} 已失败")
                            del pending_orders[order_id]
                        elif order_status == 'pending':
                            self.update_analysis_window(f"订单 {order_id} 仍在等待成交")
                        else:
                            self.update_analysis_window(f"订单 {order_id} 状态未知，考虑手动检查")
                            del pending_orders[order_id]

                item = self.data_queue.get(timeout=5)
                if 'last' in item:
                    current_price = float(item['last'])
                    current_time = time.time()
                    self.update_analysis_window(f"当前价格: {current_price}")

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
                            self.update_analysis_window(f"K线数据已更新，共{len(kline_data)}条数据")
                            self.update_analysis_window(
                                f"当前指标: MA值={self.ma_values}, 趋势MA={self.trend_ma}, ATR={self.atr}")
                        else:
                            self.update_analysis_window("无法获取K线数据")

                    buy_condition, buy_reasons = self.check_buy_condition(current_price)
                    sell_condition, sell_reasons = self.check_sell_condition(current_price)

                    self.update_analysis_window("策略分析:")
                    self.update_analysis_window(f"做多条件满足: {buy_condition}")
                    for reason in buy_reasons:
                        self.update_analysis_window(f"  - {reason}")
                    self.update_analysis_window(f"做空条件满足: {sell_condition}")
                    for reason in sell_reasons:
                        self.update_analysis_window(f"  - {reason}")

                if self.account_balance is None:
                    self.update_balance()

                if buy_condition and self.atr is not None and self.atr > 0:
                    order_result = self.open_position("buy")
                    if isinstance(order_result, dict) and 'ordId' in order_result:
                        pending_orders[order_result['ordId']] = time.time()
                    else:
                        self.update_analysis_window(f"开仓失败或返回异常结果: {order_result}")
                elif sell_condition and self.atr is not None and self.atr > 0:
                    order_result = self.open_position("sell")
                    if isinstance(order_result, dict) and 'ordId' in order_result:
                        pending_orders[order_result['ordId']] = time.time()
                    else:
                        self.update_analysis_window(f"开仓失败或返回异常结果: {order_result}")

                if self.open_positions:
                    self.manage_open_positions(current_price)

            except Empty:
                self.update_analysis_window("等待数据...")
                continue
            except Exception as e:
                self.update_analysis_window(f"发生错误: {str(e)}")
                self.update_analysis_window(f"错误详情: {traceback.format_exc()}")
                time.sleep(5)

        self.update_analysis_window("交易策略运行结束")
        self.update_analysis_window(f"最终账户余额: {self.get_account_balance()} USDT")
