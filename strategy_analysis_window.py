import datetime
import tkinter as tk
from tkinter import scrolledtext
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class StrategyAnalysisWindow:
    def __init__(self):
        self.root = None
        self.text_area = None
        self.balance_var = tk.StringVar()
        self.position_var = tk.StringVar()
        self.total_value_var = tk.StringVar()
        self.figure = None
        self.ax = None
        self.canvas = None
        self.strategy = None

    def setup(self, strategy):
        if self.root is None:
            self.root = tk.Toplevel()
            self.root.title("策略分析")
            self.root.geometry("1000x800")

            self.text_area = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, width=80, height=20)
            self.text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

            pause_button = tk.Button(self.root, text="暂停", command=strategy.pause)
            pause_button.pack(side=tk.LEFT, padx=5, pady=5)

            resume_button = tk.Button(self.root, text="恢复", command=strategy.resume)
            resume_button.pack(side=tk.LEFT, padx=5, pady=5)

            balance_label = tk.Label(self.root, textvariable=self.balance_var, font=("Helvetica", 16))
            balance_label.pack(pady=10)

            position_label = tk.Label(self.root, textvariable=self.position_var, font=("Helvetica", 16))
            position_label.pack(pady=10)

            total_value_label = tk.Label(self.root, textvariable=self.total_value_var, font=("Helvetica", 16))
            total_value_label.pack(pady=10)

            self.figure = Figure(figsize=(10, 4), dpi=100)
            self.ax = self.figure.add_subplot(111)
            self.canvas = FigureCanvasTkAgg(self.figure, master=self.root)
            self.canvas.draw()
            self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def add_message(self, message):
        if self.text_area is None:
            if self.strategy is not None:
                self.setup(self.strategy)  # 如果 self.text_area 还没有初始化,并且已经有 strategy 对象,调用 setup 方法
            else:
                return  # 如果 strategy 对象还没有设置,直接返回,不添加消息

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] {message}\n"
        self.text_area.insert(tk.END, formatted_message)

    def update_balance(self, balance, floating_profit, total_value):
        self.balance_var.set(f"当前账户余额: {balance:.2f} USDT")
        self.position_var.set(f"浮动收益: {floating_profit:.2f} USDT")
        self.total_value_var.set(f"总价值: {total_value:.2f} USDT")

    def update_chart(self, data):
        self.ax.clear()
        self.ax.plot(data['timestamps'], data['prices'], label='Price')
        self.ax.set_title("实时价格图")
        self.ax.set_xlabel("时间")
        self.ax.set_ylabel("价格")
        self.ax.legend()
        self.canvas.draw()

    def run(self, strategy):
        self.strategy = strategy
        self.setup(strategy)
        self.root.mainloop()