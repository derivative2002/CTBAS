import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QTableWidgetItem
from PyQt5.QtCore import pyqtSignal, pyqtSlot, QObject
from strategy_analysis_window_ui import Ui_CTBAS

class StrategyAnalysisWindow(QMainWindow, Ui_CTBAS):
    add_message_signal = pyqtSignal(str)
    update_balance_signal = pyqtSignal(str, float, float)
    update_position_info_signal = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.pushButton.clicked.connect(self.pause_strategy)
        self.pushButton_2.clicked.connect(self.resume_strategy)

        self.add_message_signal.connect(self.add_message)
        self.update_balance_signal.connect(self.update_balance)
        self.update_position_info_signal.connect(self.update_position_info)

    @pyqtSlot(str)
    def add_message(self, message):
        self.textEdit.append(message)

    @pyqtSlot(str, float, float)
    def update_balance(self, account_name, balance, floating_profit):
        self.label.setText(f'当前账户名称: {account_name}')
        self.label_2.setText(f'账户余额: {balance:.2f} USDT')
        self.label_3.setText(f'浮动收益: {floating_profit:.2f} USDT')

    @pyqtSlot(list)
    def update_position_info(self, positions):
        self.tableWidget.setRowCount(len(positions))
        for row, position in enumerate(positions):
            for column, data in enumerate(position):
                self.tableWidget.setItem(row, column, QTableWidgetItem(data))

    def set_strategy(self, strategy):
        self.strategy = strategy

    def pause_strategy(self):
        self.strategy.pause()

    def resume_strategy(self):
        self.strategy.resume()
