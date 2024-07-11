import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import datetime


class StrategyAnalysisWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CTBAS")
        self.root.geometry("1200x927")
        self.setup_ui()

    def setup_ui(self):
        # 主框架
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 左侧框架 - 日志输出
        left_frame = ttk.LabelFrame(main_frame, text="输出日志")
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self.text_area = tk.Text(left_frame, wrap=tk.WORD, font=("微软雅黑", 10))
        self.text_area.pack(fill=tk.BOTH, expand=True)

        # 右侧框架
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        # 基本信息框架
        info_frame = ttk.LabelFrame(right_frame, text="基本信息")
        info_frame.pack(fill=tk.X, pady=(0, 10))

        self.account_label = ttk.Label(info_frame, text="当前账户名称：", font=("微软雅黑", 12))
        self.account_label.pack(anchor=tk.W)

        self.balance_label = ttk.Label(info_frame, text="账户余额：", font=("微软雅黑", 12))
        self.balance_label.pack(anchor=tk.W)

        self.profit_label = ttk.Label(info_frame, text="浮动收益：", font=("微软雅黑", 12))
        self.profit_label.pack(anchor=tk.W)

        # 持仓管理框架
        position_frame = ttk.LabelFrame(right_frame, text="持仓管理")
        position_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 修改：更新持仓表格的列
        self.position_table = ttk.Treeview(position_frame, columns=("方向", "数量", "开仓价", "当前价", "收益"),
                                           show="headings")
        self.position_table.heading("方向", text="持仓方向")
        self.position_table.heading("数量", text="持仓量")
        self.position_table.heading("开仓价", text="开仓价")
        self.position_table.heading("当前价", text="当前价格")
        self.position_table.heading("收益", text="当前收益")
        self.position_table.pack(fill=tk.BOTH, expand=True)

        # 图表
        self.figure = plt.Figure(figsize=(6, 4), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=right_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 按钮框架
        button_frame = ttk.Frame(right_frame)
        button_frame.pack(fill=tk.X)

        self.pause_button = ttk.Button(button_frame, text="暂停", style='my.TButton')
        self.pause_button.pack(side=tk.LEFT, padx=(0, 5))

        self.resume_button = ttk.Button(button_frame, text="恢复", style='my.TButton')
        self.resume_button.pack(side=tk.LEFT)

        # 设置样式
        style = ttk.Style()
        style.configure('my.TButton', font=("微软雅黑", 12))

    # 修改：更新添加消息的方法
    def add_message(self, message):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] {message}\n"
        self.text_area.insert(tk.END, formatted_message)
        self.text_area.see(tk.END)

    # 修改：更新余额显示的方法
    def update_balance(self, balance, floating_profit, total_value):
        self.balance_label.config(text=f"账户余额：{balance:.2f} USDT")
        self.profit_label.config(text=f"浮动收益：{floating_profit:.2f} USDT")

    # 修改：更新图表的方法
    def update_chart(self, data):
        self.ax.clear()
        self.ax.plot(data['timestamps'], data['prices'])
        self.ax.set_title("实时价格图")
        self.ax.set_xlabel("时间")
        self.ax.set_ylabel("价格")
        self.canvas.draw()

    # 修改：更新持仓信息的方法
    def update_positions(self, positions):
        for i in self.position_table.get_children():
            self.position_table.delete(i)
        for position in positions:
            self.position_table.insert("", tk.END, values=(
                position['type'],
                position['size'],
                f"{position['open_price']:.2f}",
                f"{position['current_price']:.2f}",
                f"{position['profit']:.2f}"
            ))

    def setup(self, strategy):
        self.pause_button.config(command=strategy.pause)
        self.resume_button.config(command=strategy.resume)

    def run(self):
        self.root.mainloop()
