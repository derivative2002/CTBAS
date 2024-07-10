import threading
from queue import Queue
from strategy_analysis_window import StrategyAnalysisWindow
from trading_strategy import TradingStrategy
from data_collector import DataCollector
import asyncio
import sys
from PyQt5.QtWidgets import QApplication

def main():
    app = QApplication(sys.argv)

    # 创建数据队列
    data_queue = Queue()

    # 创建策略分析窗口
    analysis_window = StrategyAnalysisWindow()

    # 创建交易策略实例
    strategy = TradingStrategy(data_queue, analysis_window)

    # 设置策略实例给分析窗口
    analysis_window.set_strategy(strategy)

    # 创建数据收集器
    data_collector = DataCollector(data_queue)

    # 启动数据收集器（在新线程中）
    collector_thread = threading.Thread(target=lambda: asyncio.run(data_collector.start()), daemon=True)
    collector_thread.start()

    # 启动交易策略（在新线程中）
    strategy_thread = threading.Thread(target=strategy.start, daemon=True)
    strategy_thread.start()

    # 在主线程中运行分析窗口
    analysis_window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
