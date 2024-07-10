import asyncio
import sys
import threading
import time
from queue import Queue

from PyQt5.QtWidgets import QApplication

from data_collector import DataCollector
from strategy_analysis_window import StrategyAnalysisWindow
from trading_strategy import TradingStrategy


def main():
    app = QApplication(sys.argv)

    data_queue = Queue()
    analysis_window = StrategyAnalysisWindow()
    strategy = TradingStrategy(data_queue, analysis_window)
    analysis_window.set_strategy(strategy)
    data_collector = DataCollector(data_queue)

    collector_thread = threading.Thread(target=lambda: asyncio.run(data_collector.start()), daemon=True)
    collector_thread.start()

    strategy_thread = threading.Thread(target=strategy.run, daemon=True)
    strategy_thread.start()

    analysis_window.show()

    # 添加这个循环来保持程序运行
    while True:
        app.processEvents()
        time.sleep(0.1)


if __name__ == "__main__":
    main()
