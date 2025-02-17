import threading
import datetime
from queue import Queue
import tkinter as tk
from strategy_analysis_window import StrategyAnalysisWindow
from trading_strategy import TradingStrategy
from data_collector import DataCollector


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

    # 启动数据收集器（在新线程中）
    collector_thread = threading.Thread(target=data_collector.start)
    collector_thread.start()

    # 启动交易策略（在新线程中）
    strategy_thread = threading.Thread(target=strategy.run)
    strategy_thread.start()

    # 在主线程中运行 Tkinter 并传递 strategy 实例给 analysis_window
    analysis_window.run(strategy)

    # 等待其他线程结束
    collector_thread.join()
    strategy_thread.join()


if __name__ == "__main__":
    main()
