"""InsAuto desktop control panel (Tkinter).

Supervises the web dashboard (Streamlit) and the schedule service
(scheduler.py), can trigger a one-off auto post (worker.py), edits the
posting schedule, and shows status: Instagram session, API keys, next
and last scheduled run. All settings live in the SQLite settings table,
so this panel and the web dashboard always agree.

Usage:
    python launcher.py            # open the panel
    python launcher.py --selftest # open, auto-close after 1.5s (UI smoke test)
"""

import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from ins账号自动化 import get_settings, save_settings, SESSION_FILE
from ins账号自动化.automation import compute_next_run

try:
    from ins账号自动化.config import GEMINI_API_KEY, OPENROUTER_API_KEY
except Exception:
    GEMINI_API_KEY = OPENROUTER_API_KEY = ""

ASSETS = ROOT / "assets"
SCHED_LOCK = ROOT / "ins账号自动化" / "data" / "scheduler.lock"
APP_VERSION = "v2.2"
FLAGS = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW

BG, BG2, FG, MUTED = "#0d1117", "#161b22", "#e6edf3", "#8b949e"
GREEN, RED = "#3fb950", "#f85149"
CATEGORIES = ["(随机)", "kitchen", "home", "fitness", "beauty"]
FONT = ("Microsoft YaHei UI", 9)


class LauncherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"InsAuto 控制面板 {APP_VERSION}")
        self.configure(bg=BG)
        self.geometry("800x600")
        self.minsize(720, 520)
        self._set_icon()

        self.procs: dict[str, subprocess.Popen] = {}
        self._build_ui()
        self._load_schedule()
        self._append(f"InsAuto 控制面板 {APP_VERSION} 就绪")
        self._refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ─────────────────────────────────

    def _set_icon(self):
        try:
            ico = ASSETS / "app_icon.ico"
            if ico.exists():
                self.iconbitmap(str(ico))
        except Exception:
            pass

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG, font=FONT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT)
        style.configure("Title.TLabel", background=BG, foreground=FG,
                        font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("TCheckbutton", background=BG, foreground=FG, font=FONT)
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG, foreground=MUTED, font=FONT)
        style.configure("TButton", font=FONT)

        pad = dict(padx=14, pady=6)

        hdr = ttk.Frame(self)
        hdr.pack(fill="x", **pad)
        ttk.Label(hdr, text="🎨 InsAuto 控制面板", style="Title.TLabel").pack(side="left")
        ttk.Label(hdr, text=APP_VERSION, style="Muted.TLabel").pack(side="right")

        box = ttk.Frame(self)
        box.pack(fill="x", **pad)
        self.lbl_ig = ttk.Label(box, text="")
        self.lbl_ig.pack(anchor="w")
        self.lbl_keys = ttk.Label(box, text="")
        self.lbl_keys.pack(anchor="w")
        self.lbl_sched = ttk.Label(box, text="", style="Muted.TLabel")
        self.lbl_sched.pack(anchor="w")
        self.lbl_next = ttk.Label(box, text="")
        self.lbl_next.pack(anchor="w")

        # schedule settings
        self.var_enable = tk.BooleanVar()
        self.var_mode = tk.StringVar()
        self.var_time = tk.StringVar()
        self.var_days = tk.IntVar()
        self.var_cat = tk.StringVar()
        self.var_headless = tk.BooleanVar()

        sf = ttk.Labelframe(self, text=" 定时发布 ", padding=10)
        sf.pack(fill="x", **pad)
        r1 = ttk.Frame(sf)
        r1.pack(fill="x", pady=3)
        ttk.Checkbutton(r1, text="启用", variable=self.var_enable).pack(side="left")
        ttk.Label(r1, text="模式").pack(side="left", padx=(14, 4))
        ttk.Combobox(r1, textvariable=self.var_mode, values=["interval", "daily"],
                     width=9, state="readonly").pack(side="left")
        ttk.Label(r1, text="时间(HH:MM)").pack(side="left", padx=(14, 4))
        ttk.Entry(r1, textvariable=self.var_time, width=7).pack(side="left")
        ttk.Label(r1, text="间隔天数").pack(side="left", padx=(14, 4))
        ttk.Spinbox(r1, from_=1, to=30, textvariable=self.var_days, width=4).pack(side="left")
        r2 = ttk.Frame(sf)
        r2.pack(fill="x", pady=3)
        ttk.Label(r2, text="品类").pack(side="left")
        ttk.Combobox(r2, textvariable=self.var_cat, values=CATEGORIES,
                     width=10, state="readonly").pack(side="left", padx=(4, 14))
        ttk.Checkbutton(r2, text="后台运行浏览器（无窗口）",
                        variable=self.var_headless).pack(side="left")
        ttk.Button(r2, text="💾 保存设置", command=self._save_schedule).pack(side="right")

        # action buttons
        bf = ttk.Frame(self)
        bf.pack(fill="x", **pad)
        self._btn(bf, "▶ 启动网页面板", self._start_dashboard).pack(side="left", padx=(0, 6))
        self._btn(bf, "⏹ 停止网页", lambda: self._stop("网页")).pack(side="left", padx=(0, 6))
        self._btn(bf, "▶ 启动定时服务", self._start_scheduler).pack(side="left", padx=(0, 6))
        self._btn(bf, "⏹ 停止定时", lambda: self._stop("定时")).pack(side="left", padx=(0, 6))
        self._btn(bf, "🚀 立即发一条", self._run_once).pack(side="left", padx=(0, 6))
        self._btn(bf, "🌐 打开面板", self._open_dashboard).pack(side="left")

        # log pane
        lf = ttk.Frame(self)
        lf.pack(fill="both", expand=True, **pad)
        self.log = ScrolledText(lf, height=12, bg="#010409", fg="#c9d1d9",
                                insertbackground=FG, font=("Consolas", 9),
                                relief="flat", wrap="word")
        self.log.pack(fill="both", expand=True)

    def _btn(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd,
                         bg=BG2, fg=FG, activebackground="#21262d",
                         activeforeground=FG, relief="flat", bd=0,
                         padx=10, pady=6, cursor="hand2", font=FONT)

    # ── process management ──────────────────────────────

    def _alive(self, name: str) -> bool:
        p = self.procs.get(name)
        return bool(p and p.poll() is None)

    def _spawn(self, name: str, args: list[str]):
        if self._alive(name):
            self._append(f"[{name}] 已在运行")
            return
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", *args], cwd=str(ROOT),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=FLAGS, text=True, encoding="utf-8",
                errors="replace", bufsize=1)
        except Exception as e:
            self._append(f"[{name}] 启动失败: {e}")
            return
        self.procs[name] = proc
        self._append(f"[{name}] 已启动 (pid={proc.pid})")
        threading.Thread(target=self._pump, args=(name, proc), daemon=True).start()

    def _pump(self, name: str, proc: subprocess.Popen):
        try:
            for line in proc.stdout:
                self._append(f"[{name}] {line.rstrip()}")
        except Exception:
            pass
        self._append(f"[{name}] 进程退出 (code={proc.poll()})")

    def _stop(self, name: str):
        proc = self.procs.get(name)
        if proc and proc.poll() is None:
            proc.terminate()
            self._append(f"[{name}] 已请求停止")
        else:
            self._append(f"[{name}] 未在运行")

    def _append(self, text: str):
        def do():
            self.log.insert("end", text + "\n")
            self.log.see("end")
        try:
            self.after(0, do)
        except Exception:
            pass

    # ── actions ─────────────────────────────────────────

    def _start_dashboard(self):
        self._spawn("网页", ["-m", "streamlit", "run", str(ROOT / "app.py"),
                            "--server.headless=true",
                            "--browser.gatherUsageStats=false"])

    def _start_scheduler(self):
        self._spawn("定时", [str(ROOT / "scheduler.py")])

    def _run_once(self):
        self._spawn("发布", [str(ROOT / "worker.py")])

    def _open_dashboard(self):
        webbrowser.open("http://localhost:8501")

    # ── schedule settings ───────────────────────────────

    def _load_schedule(self):
        s = get_settings()
        self.var_enable.set(str(s.get("schedule_enabled", "0")) == "1")
        mode = s.get("schedule_mode", "interval")
        self.var_mode.set(mode if mode in ("interval", "daily") else "interval")
        self.var_time.set(s.get("scheduled_time", "10:00"))
        try:
            self.var_days.set(int(s.get("interval_days", "2") or 2))
        except Exception:
            self.var_days.set(2)
        cat = s.get("schedule_category", "") or "(随机)"
        self.var_cat.set(cat if cat in CATEGORIES else "(随机)")
        self.var_headless.set(str(s.get("scheduler_headless", "0")) == "1")

    def _save_schedule(self):
        try:
            days = int(self.var_days.get() or 2)
        except Exception:
            days = 2
        save_settings(
            schedule_enabled="1" if self.var_enable.get() else "0",
            schedule_mode=self.var_mode.get() or "interval",
            scheduled_time=(self.var_time.get() or "10:00").strip(),
            interval_days=str(days),
            schedule_category="" if self.var_cat.get() == "(随机)" else self.var_cat.get(),
            scheduler_headless="1" if self.var_headless.get() else "0",
        )
        self._append("[设置] 定时设置已保存")
        self._refresh()

    # ── status refresh ──────────────────────────────────

    def _refresh(self):
        try:
            s = get_settings()

            if SESSION_FILE.exists():
                mt = datetime.fromtimestamp(SESSION_FILE.stat().st_mtime).strftime("%m-%d %H:%M")
                self.lbl_ig.config(text=f"✅ Instagram 已登录（会话更新于 {mt}）", foreground=GREEN)
            else:
                self.lbl_ig.config(text="❌ Instagram 未登录（打开网页面板登录一次）", foreground=RED)

            or_ok = bool(OPENROUTER_API_KEY) and not OPENROUTER_API_KEY.startswith("your-")
            gm_ok = bool(GEMINI_API_KEY)
            self.lbl_keys.config(
                text=("✅ OpenRouter 已配置" if or_ok else "❌ OpenRouter 未配置") + "   ·   " +
                     ("✅ Gemini 已配置" if gm_ok else "⚠️ Gemini 未配置（免费申请 aistudio.google.com）"),
                foreground=FG if or_ok else RED)

            running = False
            try:
                running = SCHED_LOCK.exists() and (time.time() - SCHED_LOCK.stat().st_mtime) < 90
            except Exception:
                pass
            self.lbl_sched.config(
                text="🟢 定时服务运行中" if running
                else "⚪ 定时服务未运行（点「启动定时服务」或运行 启动定时发布.bat）",
                foreground=GREEN if running else MUTED)

            nxt = compute_next_run(s)
            last = s.get("schedule_last_result", "") or "无"
            if nxt:
                self.lbl_next.config(
                    text=f"📅 下次发布: {nxt.strftime('%m-%d %H:%M')}   ·   上次结果: {last}",
                    foreground=FG)
            else:
                self.lbl_next.config(text=f"⏸ 定时发布未启用   ·   上次结果: {last}",
                                     foreground=MUTED)
        except Exception:
            pass
        self.after(2000, self._refresh)

    def _on_close(self):
        running = [n for n in ("网页", "定时", "发布") if self._alive(n)]
        if running:
            ans = messagebox.askyesnocancel(
                "退出", "是否同时停止由本面板启动的进程？\n（网页 / 定时 / 发布）\n\n"
                       "是 = 停止并退出\n否 = 让它们继续后台运行并退出")
            if ans is None:
                return
            if ans:
                for n in running:
                    self._stop(n)
        self.destroy()


def main():
    app = LauncherApp()
    if "--selftest" in sys.argv:
        app.after(1500, app.destroy)
    app.mainloop()


if __name__ == "__main__":
    main()
