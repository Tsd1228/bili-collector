#!/usr/bin/env python3
"""
B站数据采集 — 图形界面版

双击运行，用户只需：
1. 点击「登录」→ 扫码
2. 等待采集完成
"""

import json
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
import sys
import os

sys.path.insert(0, str(Path(__file__).parent))

BILI_FAV_HOME = Path.home() / ".bilibili_fav"
UID_FILE = BILI_FAV_HOME / "bili_uid.txt"


class BiliApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("B站数据采集")
        self.root.geometry("420x320")
        self.root.resizable(False, False)

        # 居中显示
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 420) // 2
        y = (self.root.winfo_screenheight() - 320) // 2
        self.root.geometry(f"420x320+{x}+{y}")

        self.uid = None
        self._build_ui()
        self._check_login()

    def _build_ui(self):
        # 标题
        tk.Label(
            self.root,
            text="B站数据采集",
            font=("微软雅黑", 18, "bold"),
        ).pack(pady=(25, 5))

        # 状态文本
        self.status_var = tk.StringVar(value="正在检测登录状态...")
        self.status_label = tk.Label(
            self.root,
            textvariable=self.status_var,
            font=("微软雅黑", 11),
            fg="#666",
        )
        self.status_label.pack(pady=(5, 15))

        # 用户信息
        self.user_frame = tk.Frame(self.root)
        self.user_frame.pack()

        self.user_var = tk.StringVar(value="")
        tk.Label(
            self.user_frame,
            textvariable=self.user_var,
            font=("微软雅黑", 10),
        ).pack()

        # 按钮区
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=(20, 0))

        self.login_btn = tk.Button(
            btn_frame,
            text="登录",
            font=("微软雅黑", 12, "bold"),
            width=12,
            height=1,
            command=self._on_login,
            bg="#00a1d6",
            fg="white",
            relief="flat",
        )
        self.login_btn.pack()

        self.collect_btn = tk.Button(
            btn_frame,
            text="开始采集",
            font=("微软雅黑", 12, "bold"),
            width=12,
            height=1,
            command=self._on_collect,
            bg="#00a1d6",
            fg="white",
            relief="flat",
            state="disabled",
        )

        # 进度条
        self.progress = ttk.Progressbar(
            self.root,
            mode="indeterminate",
            length=300,
        )

        # 底部状态
        self.bottom_var = tk.StringVar(value="")
        self.bottom_label = tk.Label(
            self.root,
            textvariable=self.bottom_var,
            font=("微软雅黑", 9),
            fg="#999",
        )
        self.bottom_label.pack(side="bottom", pady=10)

    def _check_login(self):
        """检查是否已登录"""
        if not UID_FILE.exists():
            self.status_var.set("未登录，请点击下方按钮登录")
            self.login_btn.pack()
            return

        uid = UID_FILE.read_text().strip()
        user_dir = BILI_FAV_HOME / f"user_data_{uid}"
        if not user_dir.exists():
            self.status_var.set("未登录，请点击下方按钮登录")
            self.login_btn.pack()
            return

        self.uid = uid
        self.status_var.set("已登录")
        self.user_var.set(f"UID: {uid}")
        self.login_btn.pack_forget()
        self.collect_btn.pack()
        self.collect_btn.config(state="normal")

        # 检查是否有数据
        data_dir = BILI_FAV_HOME / f"data_{uid}"
        if data_dir.exists() and any(data_dir.glob("*.json")):
            self.bottom_var.set("已有采集数据，可重新采集更新")
        else:
            self.bottom_var.set("暂无数据，请点击「开始采集」")

    def _on_login(self):
        """点击登录"""
        self.login_btn.config(state="disabled", text="登录中...")
        self.status_var.set("正在打开浏览器，请扫码登录...")
        self.progress.pack(pady=(10, 0))
        self.progress.start(10)

        threading.Thread(target=self._do_login, daemon=True).start()

    def _do_login(self):
        """执行登录（后台线程）"""
        try:
            from bili_common import do_login as _do_login
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                uid = _do_login(p)

            self.uid = uid
            self.root.after(0, self._login_success)
        except Exception as e:
            self.root.after(0, lambda: self._login_fail(str(e)))

    def _login_success(self):
        """登录成功"""
        self.progress.stop()
        self.progress.pack_forget()
        self.status_var.set("登录成功！")
        self.user_var.set(f"UID: {self.uid}")
        self.login_btn.pack_forget()
        self.collect_btn.pack()
        self.collect_btn.config(state="normal")
        self.bottom_var.set("请点击「开始采集」获取数据")

    def _login_fail(self, msg):
        """登录失败"""
        self.progress.stop()
        self.progress.pack_forget()
        self.status_var.set("登录失败")
        self.login_btn.config(state="normal", text="登录")
        messagebox.showerror("登录失败", f"错误: {msg}")

    def _on_collect(self):
        """点击采集"""
        self.collect_btn.config(state="disabled", text="采集中...")
        self.status_var.set("正在采集数据，请勿关闭程序...")
        self.progress.pack(pady=(10, 0))
        self.progress.start(10)
        self.bottom_var.set("首次采集可能需要几分钟，请耐心等待")

        threading.Thread(target=self._do_collect, daemon=True).start()

    def _do_collect(self):
        """执行采集（后台线程）"""
        try:
            from bilbil import collect_favorites

            videos = collect_favorites(uid=self.uid)
            total = sum(len(v) for v in videos) if videos else 0
            self.root.after(0, lambda: self._collect_success(total))
        except Exception as e:
            self.root.after(0, lambda: self._collect_fail(str(e)))

    def _collect_success(self, total):
        """采集成功"""
        self.progress.stop()
        self.progress.pack_forget()
        self.status_var.set("采集完成！")
        self.collect_btn.config(state="normal", text="重新采集")
        self.bottom_var.set(f"共采集 {total} 个视频，数据已保存")
        messagebox.showinfo("完成", f"采集完成！\n共 {total} 个视频")

    def _collect_fail(self, msg):
        """采集失败"""
        self.progress.stop()
        self.progress.pack_forget()
        self.status_var.set("采集失败")
        self.collect_btn.config(state="normal", text="开始采集")
        messagebox.showerror("采集失败", f"错误: {msg}")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = BiliApp()
    app.run()
