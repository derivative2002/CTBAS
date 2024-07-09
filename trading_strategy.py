import logging
import time
import traceback

import numpy as np
from queue import Empty
from order_manager import OrderManager
from indicator_calculator import IndicatorCalculator
from api_client import APIClient

class TradingStrategy:
    def __init__(self, data_queue, analysis_window, config):
        self.data_queue = data_queue
        self.analysis_window = analysis_window
        self.config = config
        self.api_client = APIClient(config['api_key'], config['secret_key'], config['passphrase'], config['base_url'])
        self.logger = self.setup_logger()
        self.order_manager = OrderManager(self.api_client, self.logger)
        self.indicator_calculator = IndicatorCalculator(config['MA_PERIODS'], config['TREND_MA_PERIOD'], config['ATR_PERIOD'])
        self.initialize_strategy()

    def setup_logger(self):
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def initialize_strategy(self):
        self.open_positions = []
        self.strategy_status = "空闲"
        self.account_balance = None
        self.ma_values = np.zeros(len(self.config['MA_PERIODS']))
        self.prev_ma_values = np.zeros(len(self.config['MA_PERIODS']))
        self.trend_ma = 0
        self.atr = 0
        self.paused = False

    def log_and_update(self, message, level=logging.INFO):
        self.logger.log(level, message)
        self.analysis_window.add_message(message)

    def update_balance(self):
        self.account_balance = self.api_client.get_account_balance()
        positions_value, floating_profit = self.get_open_positions_value()
        total_value = self.account_balance + floating_profit
        self.analysis_window.update_balance(self.account_balance, floating_profit, total_value)

    def get_open_positions_value(self):
        floating_profit = 0
        for position in self.open_positions:
            current_price = self.api_client.get_current_price()
            if current_price is None:
                continue
            if position['type'] == "buy":
                profit = (current_price - position['open_price']) * position['size']
            else:  # sell
                profit = (position['open_price'] - current_price) * position['size']
            floating_profit += profit
        return 0, floating_profit

    def update_indicators(self, kline_data):
        if len(kline_data) < max(max(self.config['MA_PERIODS']), self.config['TREND_MA_PERIOD'], self.config['ATR_PERIOD'] + 1):
            self.log_and_update(f"K线数据不足，当前数据量: {len(kline_data)}", logging.WARNING)
            return

        close_prices = np.array([float(k[4]) for k in kline_data])[::-1]
        high_prices = np.array([float(k[2]) for k in kline_data])[::-1]
        low_prices = np.array([float(k[3]) for k in kline_data])[::-1]

        self.prev_ma_values = self.ma_values
        self.ma_values = self.indicator_calculator.calculate_ma(close_prices)
        self.trend_ma = self.indicator_calculator.calculate_trend_ma(close_prices)
        self.atr = self.indicator_calculator.calculate_atr(high_prices, low_prices, close_prices)

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

        if self.prev_ma_values[2] is not None and self.api_client.get_current_price() > self.prev_ma_values[2]:
            return False, ["上一根K线的收盘价未低于30日移动平均线"]

        return True, ["所有做多条件满足"]

    def check_sell_condition(self, current_price):
        if np.isnan(self.trend_ma) or current_price >= self.trend_ma:
            return False, ["价格未跌破趋势MA"]

        for ma_value in self.ma_values:
            if np.isnan(ma_value) or current_price >= ma_value:
                return False, ["价格未跌破所有MA"]

        if self.prev_ma_values[2] is not None and self.api_client.get_current_price() < self.prev_ma_values[2]:
            return False, ["上一根K线的收盘价未高于30日移动平均线"]

        return True, ["所有做空条件满足"]

    def calculate_lot_size(self, account_balance, atr):
        if atr is None or atr == 0:
            self.log_and_update("ATR 为 0，无法计算交易量", logging.WARNING)
            return None

        risk_amount = account_balance * self.config['RISK_PERCENT'] / 100.0
        stop_loss_distance = self.config['ATR_MULTIPLIER'] * atr

        current_price = self.api_client.get_current_price()
        if current_price is None:
            self.log_and_update("无法获取当前价格，无法计算交易量", logging.WARNING)
            return None

        symbol_info = self.api_client.get_symbol_info("BTC-USDT-SWAP")
        if not symbol_info or 'data' not in symbol_info or not symbol_info['data']:
            self.log_and_update("无法获取完整的交易品种信息，使用默认值", logging.WARNING)
            return None

        instrument_info = symbol_info['data'][0]
        tick_size = float(instrument_info.get('tickSz', '0.1'))
        tick_value = float(instrument_info.get('ctVal', '1'))

        risk_per_lot = stop_loss_distance / tick_size * tick_value
        lot_size = risk_amount / risk_per_lot

        self.log_and_update(f"计算的交易量: {lot_size:.4f} 手")

        return lot_size

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
        current_price = self.api_client.get_current_price()
        if current_price is None:
            self.log_and_update("无法获取当前价格，开仓失败", logging.WARNING)
            return None

        stop_loss_price = current_price - self.config[
            'ATR_MULTIPLIER'] * self.atr if order_type == "buy" else current_price + self.config[
            'ATR_MULTIPLIER'] * self.atr

        symbol_info = self.api_client.get_symbol_info("BTC-USDT-SWAP")
        if not symbol_info or 'data' not in symbol_info or not symbol_info['data']:
            self.log_and_update("无法获取交易品种信息，开仓失败", logging.ERROR)
            return None

        instrument_info = symbol_info['data'][0]
        contract_size = float(instrument_info.get('ctVal', '0.001'))
        num_contracts = lot_size / contract_size

        min_size = float(instrument_info.get('minSz', '0.1'))
        adjusted_num_contracts = max(round(num_contracts / min_size) * min_size, min_size)

        if adjusted_num_contracts < min_size:
            self.log_and_update(f"计算的交易量 ({adjusted_num_contracts:.4f} 张) 过小，无法开仓", logging.WARNING)
            return None

        order_result = self.order_manager.place_order(side, pos_side, adjusted_num_contracts, stop_loss_price)
        self.log_and_update(f"下单结果: {order_result}")

        if order_result and isinstance(order_result, list) and len(order_result) > 0:
            order_info = order_result[0]
            if order_info.get('sCode') == '0':
                order_id = order_info.get('ordId')
                if order_id:
                    order_status = self.order_manager.check_order_status(order_id)

                    if order_status == 'filled':
                        position = {
                            'type': order_type,
                            'open_price': float(order_info.get('avgPx', current_price)),
                            'size': lot_size,
                            'open_time': time.time(),
                            'stop_loss_price': stop_loss_price,
                            'take_profit_price': 0,
                        }

                        position['take_profit_price'] = position['open_price'] + self.config[
                            'TAKE_PROFIT'] * self.atr if order_type == "buy" else position['open_price'] - self.config[
                            'TAKE_PROFIT'] * self.atr

                        self.open_positions.append(position)

                        self.log_and_update(
                            f"开仓成功: {order_type.capitalize()}单已成交, 手数={lot_size:.4f} (合约张数: {adjusted_num_contracts:.4f}), 开仓价={position['open_price']:.2f},"
                            f"初始止损价={position['stop_loss_price']:.2f}, 初始止盈价={position['take_profit_price']:.2f}")

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

    def close_position(self, position):
        if not self.open_positions:
            self.log_and_update("没有持仓可以平仓", logging.WARNING)
            return False

        current_price = self.api_client.get_current_price()
        if current_price is None:
            self.log_and_update("无法获取当前价格，平仓失败", logging.WARNING)
            return False

        side = "sell" if position['type'] == "buy" else "buy"
        pos_side = "long" if position['type'] == "buy" else "short"

        symbol_info = self.api_client.get_symbol_info("BTC-USDT-SWAP")
        if not symbol_info or 'data' not in symbol_info or not symbol_info['data']:
            self.log_and_update("无法获取交易品种信息，平仓失败", logging.ERROR)
            return False

        instrument_info = symbol_info['data'][0]
        contract_val = float(instrument_info.get('ctVal', '0.001'))
        num_contracts = position['size'] / contract_val
        min_size = float(instrument_info.get('minSz', '0.1'))
        adjusted_num_contracts = max(round(num_contracts / min_size) * min_size, min_size)

        order_result = self.order_manager.place_order(side, pos_side, adjusted_num_contracts)
        self.log_and_update(f"平仓下单结果: {order_result}")

        if order_result and isinstance(order_result, list) and len(order_result) > 0:
            order_info = order_result[0]
            if order_info.get('sCode') == '0':
                order_id = order_info.get('ordId')
                if order_id:
                    order_status = self.order_manager.check_order_status(order_id)

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

    def manage_open_positions(self, current_price):
        for position in self.open_positions:
            if position is None or position['open_time'] is None:
                continue

            if (time.time() - position['open_time']) < 5:
                continue

            if position['type'] == "buy":
                profit = (current_price - position['open_price']) * position['size']
                profit_percentage = (current_price - position['open_price']) / position['open_price'] * 100
                new_stop_loss = max(position['stop_loss_price'],
                                    position['open_price'] - self.config['ATR_MULTIPLIER'] * self.atr)
                new_take_profit = max(position['take_profit_price'],
                                      position['open_price'] + self.config['TAKE_PROFIT'] * self.atr)
                should_close = current_price <= new_stop_loss * 0.99 or current_price >= new_take_profit * 1.01
            elif position['type'] == "sell":
                profit = (position['open_price'] - current_price) * position['size']
                profit_percentage = (position['open_price'] - current_price) / position['open_price'] * 100
                new_stop_loss = min(position['stop_loss_price'],
                                    position['open_price'] + self.config['ATR_MULTIPLIER'] * self.atr)
                new_take_profit = min(position['take_profit_price'],
                                      position['open_price'] - self.config['TAKE_PROFIT'] * self.atr)
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
        self.account_balance = self.api_client.get_account_balance()
        if self.account_balance is None:
            self.log_and_update("无法获取账户余额，策略停止运行", logging.ERROR)
            return

        last_kline_update = 0
        kline_update_interval = 1  # 每1秒更新一次K线数据
        timestamps = []
        prices = []

        trade_count = 0
        last_check_time = time.time()
        pending_orders = {}

        while True:
            if self.paused:
                time.sleep(1)
                continue

            try:
                current_time = time.time()
                time_diff = current_time - last_check_time

                if time_diff >= 1800:
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
                        order_status = self.order_manager.check_order_status(order_id)
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

                    timestamps.append(time.time())
                    prices.append(current_price)
                    if len(timestamps) > 100:
                        timestamps.pop(0)
                        prices.pop(0)
                    self.analysis_window.update_chart({'timestamps': timestamps, 'prices': prices})

                    if current_time - last_kline_update >= kline_update_interval:
                        kline_data = self.api_client.get_kline_data(
                            max(max(self.config['MA_PERIODS']), self.config['TREND_MA_PERIOD'],
                                self.config['ATR_PERIOD'] + 1))
                        if kline_data and 'data' in kline_data:
                            self.update_indicators(kline_data['data'])
                            last_kline_update = current_time
                        self.log_and_update(f"K线数据已更新，共{len(kline_data['data'])}条数据")
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
            self.log_and_update(f"最终账户余额: {self.api_client.get_account_balance()} USDT")