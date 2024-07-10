import datetime
import tkinter as tk
from tkinter import scrolledtext, ttk, font

class StrategyAnalysisWindow:
    def __init__(self):
        self.root = None
        self.text_area = None
        self.balance_var = tk.StringVar()
        self.position_var = tk.StringVar()
        self.total_value_var = tk.StringVar()
        self.position_info_text = None
        self.strategy = None
        self.current_font_size = 12

    def setup(self, strategy):
        if self.root is None:
            self.root = tk.Toplevel()
            self.root.title("策略分析")
            self.root.geometry("1200x800")

            # 使用frame来组织布局
            main_frame = ttk.Frame(self.root, padding="10 10 10 10")
            main_frame.pack(fill=tk.BOTH, expand=True)

            # 左边日志区域
            left_frame = ttk.Frame(main_frame)
            left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.text_area = scrolledtext.ScrolledText(left_frame, wrap=tk.WORD, width=60, height=40, font=("Helvetica", self.current_font_size))
            self.text_area.pack(fill=tk.BOTH, expand=True)

            # 右边区域
            right_frame = ttk.Frame(main_frame)
            right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

            # 右上角账户信息区域
            info_frame = ttk.Frame(right_frame)
            info_frame.pack(side=tk.TOP, fill=tk.X)
            balance_label = ttk.Label(info_frame, textvariable=self.balance_var, font=("Helvetica", 16))
            balance_label.pack(side=tk.TOP, pady=5)
            position_label = ttk.Label(info_frame, textvariable=self.position_var, font=("Helvetica", 16))
            position_label.pack(side=tk.TOP, pady=5)
            total_value_label = ttk.Label(info_frame, textvariable=self.total_value_var, font=("Helvetica", 16))
            total_value_label.pack(side=tk.TOP, pady=5)

            # 右下角持仓管理区域
            position_frame = ttk.Frame(right_frame)
            position_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True)
            position_label = ttk.Label(position_frame, text="当前持仓信息", font=("Helvetica", 16))
            position_label.pack(side=tk.TOP, pady=5)
            self.position_info_text = scrolledtext.ScrolledText(position_frame, wrap=tk.WORD, width=60, height=20, font=("Helvetica", self.current_font_size))
            self.position_info_text.pack(fill=tk.BOTH, expand=True)

            # 控制按钮和字体大小调整
            control_frame = ttk.Frame(main_frame)
            control_frame.pack(side=tk.TOP, fill=tk.X)
            increase_font_button = ttk.Button(control_frame, text="增加字体大小", command=self.increase_font_size)
            increase_font_button.pack(side=tk.LEFT, padx=5, pady=5)
            decrease_font_button = ttk.Button(control_frame, text="减少字体大小", command=self.decrease_font_size)
            decrease_font_button.pack(side=tk.LEFT, padx=5, pady=5)

    def increase_font_size(self):
        self.current_font_size += 2
        self.update_font_size()

    def decrease_font_size(self):
        if self.current_font_size > 8:
            self.current_font_size -= 2
            self.update_font_size()

    def update_font_size(self):
        new_font = font.Font(size=self.current_font_size)
        self.text_area.configure(font=new_font)
        self.position_info_text.configure(font=new_font)

    def add_message(self, message):
        if self.text_area is None:
            if self.strategy is not None:
                self.setup(self.strategy)  # 如果 self.text_area 还没有初始化,并且已经有 strategy 对象,调用 setup 方法
            else:
                return  # 如果 strategy 对象还没有设置,直接返回,不添加消息

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] {message}\n"
        self.text_area.insert(tk.END, formatted_message)
        self.text_area.see(tk.END)  # 滚动到最新消息

    def update_balance(self, balance, floating_profit, total_value):
        self.balance_var.set(f"当前账户余额: {balance:.2f} USDT")
        self.position_var.set(f"浮动收益: {floating_profit:.2f} USDT")
        self.total_value_var.set(f"总价值: {total_value:.2f} USDT")

    def update_position_info(self, position_info):
        if self.position_info_text is not None:
            self.position_info_text.delete(1.0, tk.END)  # 清空当前内容
            self.position_info_text.insert(tk.END, position_info)
            self.position_info_text.see(tk.END)  # 滚动到最新消息

    def run(self, strategy):
        self.strategy = strategy
        self.setup(strategy)
        self.root.mainloop()
