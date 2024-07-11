import threading
import tkinter as tk
from queue import Queue
from strategy_analysis_window import StrategyAnalysisWindow
from trading_strategy import TradingStrategy
from data_collector import DataCollector
import asyncio

def run_async_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

def main():
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口

    # 创建数据队列
    data_queue = Queue()

    # 创建策略分析窗口
    analysis_window = StrategyAnalysisWindow()

    # 创建交易策略实例
    strategy = TradingStrategy(data_queue, analysis_window)

    # 创建数据收集器
    data_collector = DataCollector(data_queue)

    # 创建新的事件循环
    loop = asyncio.new_event_loop()

    # 启动数据收集器（在新线程中）
    collector_thread = threading.Thread(target=run_async_loop, args=(loop,))
    collector_thread.start()

    # 在事件循环中启动数据收集器
    asyncio.run_coroutine_threadsafe(data_collector.start(), loop)

    # 启动交易策略（在新线程中）
    strategy_thread = threading.Thread(target=strategy.run)
    strategy_thread.start()

    # 设置策略对象
    analysis_window.setup(strategy)

    # 在主线程中运行 Tkinter
    analysis_window.run()

    # 停止事件循环
    loop.call_soon_threadsafe(loop.stop)

    # 等待其他线程结束
    collector_thread.join()
    strategy_thread.join()

if __name__ == "__main__":
    main()