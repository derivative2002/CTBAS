import datetime
from queue import Queue
import tkinter as tk
from tkinter import scrolledtext
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class StrategyAnalysisWindow:
    def __init__(self):
        self.root = None
        self.text_area = None
        self.message_queue = Queue()
        self.counter = 1
        self.balance_var = tk.StringVar()
        self.figure = None
        self.ax = None
        self.canvas = None

    def setup(self, strategy):
        self.root = tk.Toplevel()
        self.root.title("策略分析")
        self.root.geometry("1000x800")

        self.text_area = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, width=80, height=20)
        self.text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # 添加暂停和恢复按钮
        pause_button = tk.Button(self.root, text="暂停", command=strategy.pause)
        pause_button.pack(side=tk.LEFT, padx=5, pady=5)

        resume_button = tk.Button(self.root, text="恢复", command=strategy.resume)
        resume_button.pack(side=tk.LEFT, padx=5, pady=5)

        # 添加显示账户余额的标签
        balance_label = tk.Label(self.root, textvariable=self.balance_var, font=("Helvetica", 16))
        balance_label.pack(pady=10)

        # 创建图表
        self.figure = Figure(figsize=(10, 4), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.root)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.update_text()

    def add_message(self, message):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"{self.counter}. [{timestamp}] {message}\n"
        self.message_queue.put(formatted_message)
        self.counter += 1

    def update_text(self):
        while not self.message_queue.empty():
            message = self.message_queue.get()
            self.text_area.insert(tk.END, message)
            self.text_area.see(tk.END)
        self.root.after(100, self.update_text)

    def update_balance(self, balance):
        self.balance_var.set(f"当前账户余额: {balance:.2f} USDT")

    def update_chart(self, data):
        self.ax.clear()
        self.ax.plot(data['timestamps'], data['prices'], label='Price')
        self.ax.set_title("实时价格图")
        self.ax.set_xlabel("时间")
        self.ax.set_ylabel("价格")
        self.ax.legend()
        self.canvas.draw()

    def run(self, strategy):
        self.setup(strategy)
        self.root.mainloop()
