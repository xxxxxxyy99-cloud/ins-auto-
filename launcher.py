"""InsAuto Launcher v2 — Desktop control panel with image generation."""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import io
import os
import sys
import time
import random
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# ── Theme ────────────────────────────────────────────────

BG       = "#0d1117"
BG2      = "#161b22"
BG3      = "#21262d"
ACCENT   = "#58a6ff"
GREEN    = "#3fb950"
ORANGE   = "#d29922"
RED      = "#f85149"
PURPLE   = "#a371f7"
TEXT     = "#e6edf3"
TEXT2    = "#8b949e"
BORDER   = "#30363d"
CARD_BG  = "#1c2128"

FONT_H1  = ("Segoe UI", 20, "bold")
FONT_H2  = ("Segoe UI", 13, "bold")
FONT_BODY = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 8)
FONT_MONO = ("Consolas", 9)
FONT_BTN = ("Segoe UI", 10, "bold")


class LoginPage:
    def __init__(self, root, on_login):
        self.root = root
        self.on_login = on_login
        self._build()

    def _build(self):
        self.frame = tk.Frame(self.root, bg=BG)
        self.frame.place(relx=0.5, rely=0.5, anchor="center")

        # Logo
        tk.Label(self.frame, text="🎨", font=("Segoe UI", 40),
                 bg=BG, fg=ACCENT).pack(pady=(0, 4))
        tk.Label(self.frame, text="InsAuto", font=FONT_H1,
                 bg=BG, fg=ACCENT).pack(pady=(0, 2))
        tk.Label(self.frame, text="AI 驱动的 Instagram 内容自动化",
                 font=("Segoe UI", 10), bg=BG, fg=TEXT2).pack(pady=(0, 24))

        # Form
        form = tk.Frame(self.frame, bg=BG2, padx=32, pady=24,
                        highlightbackground=BORDER, highlightthickness=1)
        form.pack()

        tk.Label(form, text="🔐 登录 Instagram", font=FONT_H2,
                 bg=BG2, fg=TEXT).pack(pady=(0, 16))

        # Username
        tk.Label(form, text="用户名", font=FONT_SMALL, bg=BG2, fg=TEXT2, anchor="w").pack(fill="x")
        self.username_entry = tk.Entry(
            form, font=FONT_BODY, bg=BG, fg=TEXT, insertbackground=TEXT,
            bd=0, highlightbackground=BORDER, highlightthickness=1, width=30)
        self.username_entry.pack(fill="x", pady=(2, 12), ipady=6)

        # Session ID
        tk.Label(form, text="Session ID", font=FONT_SMALL, bg=BG2, fg=TEXT2, anchor="w").pack(fill="x")
        self.session_entry = tk.Entry(
            form, font=FONT_BODY, bg=BG, fg=TEXT, insertbackground=TEXT,
            bd=0, highlightbackground=BORDER, highlightthickness=1, width=30,
            show="•")
        self.session_entry.pack(fill="x", pady=(2, 4), ipady=6)

        tk.Label(form,
            text="F12 → Application → Cookies → 复制 sessionid 值",
            font=FONT_SMALL, bg=BG2, fg=TEXT2).pack(anchor="w", pady=(0, 18))

        # Buttons
        self.login_btn = tk.Button(
            form, text="🔗 连接 Instagram", font=FONT_BTN,
            bg=GREEN, fg="white", activebackground="#2ea043",
            activeforeground="white", bd=0, cursor="hand2",
            padx=20, pady=10, command=self._do_login)
        self.login_btn.pack(fill="x")

        self.demo_btn = tk.Button(
            form, text="🎮 离线模式（仅生图）", font=FONT_BTN,
            bg=BG3, fg=TEXT2, activebackground=BG2,
            activeforeground=TEXT, bd=0, cursor="hand2",
            padx=20, pady=6, command=self._do_demo)
        self.demo_btn.pack(fill="x", pady=(6, 0))

        self.error_label = tk.Label(form, text="", font=FONT_SMALL, bg=BG2, fg=RED)
        self.error_label.pack(pady=(8, 0))

        # Key bindings
        self.username_entry.bind("<Return>", lambda e: self.session_entry.focus())
        self.session_entry.bind("<Return>", lambda e: self._do_login())

    def _do_login(self):
        username = self.username_entry.get().strip()
        sessionid = self.session_entry.get().strip()
        if not username or not sessionid:
            self.error_label.config(text="请填写用户名和 Session ID")
            return
        self._set_loading(True)

        def worker():
            try:
                from ins账号自动化.bot import login
                login(username=username, sessionid=sessionid)
                self.root.after(0, lambda: self.on_login(username))
            except Exception as e:
                self.root.after(0, lambda: self._login_failed(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _do_demo(self):
        self.on_login("demo_user")

    def _set_loading(self, loading):
        state = "disabled" if loading else "normal"
        self.login_btn.config(state=state, text="⏳ 登录中..." if loading else "🔗 连接 Instagram")
        self.demo_btn.config(state=state)

    def _login_failed(self, msg):
        self._set_loading(False)
        self.error_label.config(text=msg[:100])

    def destroy(self):
        self.frame.destroy()


class MainPage:
    def __init__(self, root, username, on_logout):
        self.root = root
        self.username = username
        self.on_logout = on_logout
        self._running_task = False
        self._refresh_job = None
        self._active_tab = "dashboard"
        self._build()
        self._refresh_status()

    # ── Layout ──────────────────────────────────────────

    def _build(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        self._build_header()
        self._build_sidebar()
        self._build_content()
        self._build_footer()

    def _build_header(self):
        h = tk.Frame(self.root, bg=BG2, height=60)
        h.grid(row=0, column=0, columnspan=2, sticky="ew")
        h.grid_propagate(False)

        tk.Label(h, text="🎨 InsAuto", font=("Segoe UI", 16, "bold"),
                 bg=BG2, fg=ACCENT).place(x=18, y=12)
        tk.Label(h, text=f"@{self.username}", font=FONT_SMALL,
                 bg=BG2, fg=TEXT2).place(x=18, y=38)

        # Right-side: status indicator + logout
        right = tk.Frame(h, bg=BG2)
        right.place(relx=1, x=-14, y=18, anchor="ne")

        self._status_dot = tk.Canvas(right, width=8, height=8,
                                     highlightthickness=0, bg=BG2)
        self._status_dot.grid(row=0, column=0, padx=(0, 4))
        self._dot_circle = self._status_dot.create_oval(0, 0, 8, 8, fill=TEXT2, outline="")

        self._status_lbl = tk.Label(right, text="检查中", font=FONT_SMALL, bg=BG2, fg=TEXT2)
        self._status_lbl.grid(row=0, column=1, padx=(0, 12))

        tk.Button(right, text="退出", font=FONT_SMALL, bg=BG2, fg=TEXT2,
                  bd=1, cursor="hand2", activebackground=BG3, activeforeground=RED,
                  highlightbackground=BORDER, padx=10, pady=2,
                  command=on_logout).grid(row=0, column=2)

        # Separator
        sep = tk.Frame(self.root, bg=BORDER, height=1)
        sep.grid(row=1, column=0, columnspan=2, sticky="ew")

    def _build_sidebar(self):
        sidebar = tk.Frame(self.root, bg=BG2, width=160)
        sidebar.grid(row=2, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)

        tabs = [
            ("📊 仪表盘", "dashboard"),
            ("🎬 图片工作室", "studio"),
            ("📋 发布队列", "queue"),
            ("📜 历史", "history"),
        ]
        self._tab_buttons = {}
        for text, key in tabs:
            btn = tk.Button(sidebar, text=f"  {text}", font=("Segoe UI", 10),
                           bg=BG2, fg=TEXT2, bd=0, cursor="hand2",
                           anchor="w", padx=16, pady=8,
                           activebackground=BG3, activeforeground=TEXT,
                           command=lambda k=key: self._switch_tab(k))
            btn.pack(fill="x", pady=(2, 0))
            self._tab_buttons[key] = btn

        # Highlight active
        self._tab_buttons["dashboard"].config(bg=BG3, fg=ACCENT)

        # Separator + status
        tk.Frame(sidebar, bg=BORDER, height=1).pack(fill="x", pady=12)

        # Quick status
        self._sidebar_q = tk.Label(sidebar, text="队列: —", font=FONT_SMALL,
                                   bg=BG2, fg=TEXT2, anchor="w")
        self._sidebar_q.pack(fill="x", padx=16)
        self._sidebar_gen = tk.Label(sidebar, text="生成: —", font=FONT_SMALL,
                                     bg=BG2, fg=TEXT2, anchor="w")
        self._sidebar_gen.pack(fill="x", padx=16)

    def _build_content(self):
        self._content_frame = tk.Frame(self.root, bg=BG)
        self._content_frame.grid(row=2, column=1, sticky="nsew", padx=16, pady=12)
        self._content_frame.columnconfigure(0, weight=1)
        self._content_frame.rowconfigure(0, weight=1)
        self._content_frame.rowconfigure(1, weight=1)

        # Top: card + actions
        self._top_frame = tk.Frame(self._content_frame, bg=BG)
        self._top_frame.grid(row=0, column=0, sticky="new")

        # Bottom: log
        self._log_frame = tk.Frame(self._content_frame, bg=BG)
        self._log_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self._log_frame.columnconfigure(0, weight=1)
        self._log_frame.rowconfigure(1, weight=1)
        self._build_log()

        # Default: dashboard
        self._show_dashboard()

    def _build_footer(self):
        f = tk.Frame(self.root, bg=BG2, height=26)
        f.grid(row=3, column=0, columnspan=2, sticky="ew")
        f.grid_propagate(False)
        tk.Label(f, text="InsAuto v2.0 · Multi-Provider Image Gen",
                 font=FONT_SMALL, bg=BG2, fg=TEXT2).pack(side="left", padx=12)
        self._clock = tk.Label(f, text="", font=FONT_SMALL, bg=BG2, fg=TEXT2)
        self._clock.pack(side="right", padx=12)
        self._tick()

    def _build_log(self):
        hdr = tk.Frame(self._log_frame, bg=BG)
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        tk.Label(hdr, text="📄 输出日志", font=FONT_SMALL, fg=TEXT2, bg=BG).pack(side="left")
        tk.Button(hdr, text="清空", font=FONT_SMALL, bg=BG3, fg=TEXT2,
                  bd=1, cursor="hand2", highlightbackground=BORDER, padx=8,
                  command=self._clear_log).pack(side="right")

        log_bg = tk.Frame(self._log_frame, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
        log_bg.grid(row=1, column=0, sticky="nsew")
        log_bg.columnconfigure(0, weight=1)
        log_bg.rowconfigure(0, weight=1)

        self._log_text = tk.Text(log_bg, font=FONT_MONO, bg=BG2, fg=TEXT2,
                                 bd=0, padx=10, pady=8, height=8,
                                 relief="flat", state="disabled", wrap="word")
        self._log_text.grid(row=0, column=0, sticky="nsew")

        scroll = tk.Scrollbar(log_bg, command=self._log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self._log_text.config(yscrollcommand=scroll.set)

    # ── Tab switching ───────────────────────────────────

    def _switch_tab(self, key):
        self._active_tab = key
        for k, btn in self._tab_buttons.items():
            if k == key:
                btn.config(bg=BG3, fg=ACCENT)
            else:
                btn.config(bg=BG2, fg=TEXT2)

        # Clear top frame
        for w in self._top_frame.winfo_children():
            w.destroy()

        if key == "dashboard":
            self._show_dashboard()
        elif key == "studio":
            self._show_studio()
        elif key == "queue":
            self._show_queue()
        elif key == "history":
            self._show_history()

    # ── Dashboard ───────────────────────────────────────

    def _show_dashboard(self):
        # Stats cards
        cards_frame = tk.Frame(self._top_frame, bg=BG)
        cards_frame.pack(fill="x", pady=(4, 12))
        for i in range(4):
            cards_frame.columnconfigure(i, weight=1, uniform="card")

        self._cards = {}
        for i, (icon, label, color) in enumerate([
            ("📦", "待发布", ACCENT),
            ("✅", "已发布", GREEN),
            ("🎨", "已生成", ORANGE),
            ("⚠️", "错误", RED),
        ]):
            card = tk.Frame(cards_frame, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
            card.grid(row=0, column=i, sticky="ew", padx=4, ipady=2)
            inner = tk.Frame(card, bg=CARD_BG, padx=14, pady=10)
            inner.pack(fill="x")
            tk.Label(inner, text=icon, font=("Segoe UI", 16), bg=CARD_BG, fg=color).pack(anchor="w")
            val = tk.Label(inner, text="—", font=("Segoe UI", 24, "bold"), bg=CARD_BG, fg=TEXT)
            val.pack(anchor="w")
            tk.Label(inner, text=label, font=FONT_SMALL, bg=CARD_BG, fg=TEXT2).pack(anchor="w")
            self._cards[label] = val

        # Actions
        actions = tk.Frame(self._top_frame, bg=BG)
        actions.pack(fill="x", pady=(0, 8))

        tk.Label(actions, text="快捷操作", font=FONT_H2, bg=BG, fg=TEXT).pack(anchor="w", pady=(0, 8))

        btn_grid = tk.Frame(actions, bg=BG)
        btn_grid.pack(fill="x")
        for i in range(4):
            btn_grid.columnconfigure(i, weight=1, uniform="btn")

        self._task_btns = []
        buttons = [
            ("🌐 打开仪表盘", self._open_dashboard, ACCENT, "Web 控制台"),
            ("🎨 生成 3 张", self._gen_batch, GREEN, "AI 生图入队"),
            ("📤 发布 1 篇", self._post_one, ORANGE, "从队列发布"),
            ("⏱ 定时任务", self._run_scheduler, PURPLE, "自动循环发布"),
        ]
        for i, (text, cmd, color, desc) in enumerate(buttons):
            card = tk.Frame(btn_grid, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
            card.grid(row=0, column=i, sticky="ew", padx=3)
            inner = tk.Frame(card, bg=CARD_BG, padx=2, pady=3)
            inner.pack(fill="x")
            btn = tk.Button(inner, text=text, font=FONT_BTN, bg=color, fg="white",
                           activebackground=color, activeforeground="white",
                           bd=0, cursor="hand2", command=cmd, padx=8, pady=8)
            btn.pack(fill="x")
            tk.Label(inner, text=desc, font=FONT_SMALL, bg=CARD_BG, fg=TEXT2).pack(pady=(0, 4))
            self._task_btns.append(btn)

    # ── Studio Tab ──────────────────────────────────────

    def _show_studio(self):
        f = tk.Frame(self._top_frame, bg=BG)
        f.pack(fill="both", expand=True)

        tk.Label(f, text="🎬 图片工作室", font=FONT_H2, bg=BG, fg=TEXT).pack(anchor="w")

        # Product selector
        row1 = tk.Frame(f, bg=BG)
        row1.pack(fill="x", pady=(10, 4))

        tk.Label(row1, text="产品:", font=FONT_BODY, bg=BG, fg=TEXT2).pack(side="left", padx=(0, 8))

        from ins账号自动化.content import DEFAULT_CATEGORIES
        all_products = []
        for cat_products in DEFAULT_CATEGORIES.values():
            all_products.extend(cat_products)

        self._studio_product = tk.StringVar(value=all_products[0] if all_products else "lemon press")
        self._studio_count = tk.IntVar(value=3)

        combo = ttk.Combobox(row1, textvariable=self._studio_product,
                            values=all_products, font=FONT_BODY,
                            state="readonly", width=24)
        combo.pack(side="left", padx=(0, 16))

        tk.Label(row1, text="数量:", font=FONT_BODY, bg=BG, fg=TEXT2).pack(side="left", padx=(0, 8))
        tk.Spinbox(row1, from_=1, to=10, textvariable=self._studio_count,
                  font=FONT_BODY, width=5, bg=BG2, fg=TEXT).pack(side="left")

        # Custom prompt
        tk.Label(f, text="自定义 Prompt（可选）:", font=FONT_BODY, bg=BG, fg=TEXT2).pack(anchor="w", pady=(10, 2))
        self._studio_prompt_entry = tk.Text(f, font=FONT_MONO, bg=BG2, fg=TEXT,
                                            bd=0, highlightbackground=BORDER,
                                            highlightthickness=1, height=3,
                                            padx=8, pady=6, wrap="word")
        self._studio_prompt_entry.pack(fill="x")

        # Generate button
        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack(fill="x", pady=(10, 4))

        tk.Button(btn_row, text="🎨 生成图片", font=FONT_BTN, bg=GREEN, fg="white",
                  activebackground="#2ea043", activeforeground="white",
                  bd=0, cursor="hand2", padx=20, pady=8,
                  command=self._studio_generate).pack(side="left", padx=(0, 10))

        tk.Button(btn_row, text="📋 全部加入队列", font=FONT_BTN, bg=ACCENT, fg="white",
                  activebackground=ACCENT, activeforeground="white",
                  bd=0, cursor="hand2", padx=20, pady=8,
                  command=self._studio_queue_all).pack(side="left")

        # Preview area
        tk.Label(f, text="生成结果:", font=FONT_BODY, bg=BG, fg=TEXT2).pack(anchor="w", pady=(8, 4))
        self._studio_preview = tk.Frame(f, bg=BG)
        self._studio_preview.pack(fill="both", expand=True)

    def _studio_generate(self):
        self._run_task(self._do_studio_generate)

    def _do_studio_generate(self):
        from ins账号自动化.content import generate_prompt, generate_batch
        product = self._studio_product.get()
        count = self._studio_count.get()
        custom = self._studio_prompt_entry.get("1.0", "end-1c").strip()

        if custom:
            prompt = custom
        else:
            settings = self._get_settings()
            prompt, _ = generate_prompt(product=product, niche=settings.get("niche", ""))

        self._log(f"生成 {count} 张: {product}")
        paths = generate_batch(prompt=prompt, count=count)

        # Store for queue button
        self._last_generated = paths
        self._last_product = product
        self._last_prompt = prompt

        for p in paths:
            self._log(f"  ✓ {Path(p).name}")

        # Show file paths in preview
        def update_preview():
            for w in self._studio_preview.winfo_children():
                w.destroy()
            for i, p in enumerate(paths):
                tk.Label(self._studio_preview,
                        text=f"#{i+1} {Path(p).name}",
                        font=FONT_SMALL, bg=BG, fg=TEXT2).pack(anchor="w")
                tk.Label(self._studio_preview,
                        text=f"     {p}",
                        font=FONT_SMALL, bg=BG, fg=TEXT2).pack(anchor="w")
            tk.Label(self._studio_preview,
                    text=f"\n共 {len(paths)} 张图片已生成",
                    font=FONT_BODY, bg=BG, fg=GREEN).pack(anchor="w", pady=(4, 0))
        self.root.after(0, update_preview)

    def _studio_queue_all(self):
        if not getattr(self, '_last_generated', None):
            messagebox.showwarning("提示", "请先生成图片")
            return
        self._run_task(self._do_studio_queue_all)

    def _do_studio_queue_all(self):
        from ins账号自动化.content import generate_caption, build_caption
        settings = self._get_settings()
        hashtags_raw = settings.get("hashtags", "")

        for path in self._last_generated:
            cap = generate_caption(
                self._last_product, style=settings.get("style", "casual"),
                niche=settings.get("audience", ""),
                model=settings.get("llm_model", "qwen/qwen-2.5-7b-instruct"),
                instructions=settings.get("caption_instructions", ""),
            )
            if hashtags_raw.strip():
                cap = build_caption(cap, hashtags_raw.split())
            from ins账号自动化 import db
            db.queue_push(path, str(cap), self._last_product)
            db.analytics_increment("generated")
            self._log(f"  入队: {self._last_product}")

        self._log(f"✓ {len(self._last_generated)} 条已加入队列")
        self.root.after(0, self._refresh_status)

    # ── Queue Tab ───────────────────────────────────────

    def _show_queue(self):
        f = tk.Frame(self._top_frame, bg=BG)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="📋 发布队列", font=FONT_H2, bg=BG, fg=TEXT).pack(anchor="w")

        self._queue_list = tk.Frame(f, bg=BG)
        self._queue_list.pack(fill="both", expand=True, pady=(8, 0))
        self._refresh_queue_display()

        # Action buttons
        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack(fill="x", pady=(8, 0))
        tk.Button(btn_row, text="📤 发布全部", font=FONT_BTN, bg=GREEN, fg="white",
                  bd=0, cursor="hand2", padx=16, pady=6,
                  command=self._post_all).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="🗑️ 清空队列", font=FONT_BTN, bg=RED, fg="white",
                  bd=0, cursor="hand2", padx=16, pady=6,
                  command=self._clear_queue).pack(side="left")

    def _refresh_queue_display(self):
        if not hasattr(self, '_queue_list'):
            return
        for w in self._queue_list.winfo_children():
            w.destroy()
        try:
            from ins账号自动化 import get_queue
            q = get_queue()
            if not q:
                tk.Label(self._queue_list, text="队列为空", font=FONT_BODY,
                        bg=BG, fg=TEXT2).pack(pady=20)
            else:
                for i, entry in enumerate(q[:20]):
                    item = tk.Frame(self._queue_list, bg=CARD_BG,
                                   highlightbackground=BORDER, highlightthickness=1)
                    item.pack(fill="x", pady=2, ipady=2)
                    inner = tk.Frame(item, bg=CARD_BG, padx=10, pady=4)
                    inner.pack(fill="x")
                    tk.Label(inner, text=f"#{i+1} {entry.get('product','?')}",
                            font=FONT_BODY, bg=CARD_BG, fg=TEXT).pack(anchor="w")
                    cap = entry.get("caption", "")[:60]
                    tk.Label(inner, text=cap, font=FONT_SMALL, bg=CARD_BG, fg=TEXT2).pack(anchor="w")
        except Exception as e:
            tk.Label(self._queue_list, text=f"加载失败: {e}",
                    font=FONT_SMALL, bg=BG, fg=RED).pack()

    # ── History Tab ─────────────────────────────────────

    def _show_history(self):
        f = tk.Frame(self._top_frame, bg=BG)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="📜 发布历史", font=FONT_H2, bg=BG, fg=TEXT).pack(anchor="w")

        hist_frame = tk.Frame(f, bg=BG)
        hist_frame.pack(fill="both", expand=True, pady=(8, 0))

        try:
            from ins账号自动化 import get_history
            h = get_history()
            if not h:
                tk.Label(hist_frame, text="暂无发布记录", font=FONT_BODY,
                        bg=BG, fg=TEXT2).pack(pady=20)
            else:
                for i, entry in enumerate(reversed(h[-30:])):
                    item = tk.Frame(hist_frame, bg=CARD_BG,
                                   highlightbackground=BORDER, highlightthickness=1)
                    item.pack(fill="x", pady=2, ipady=2)
                    inner = tk.Frame(item, bg=CARD_BG, padx=10, pady=4)
                    inner.pack(fill="x")
                    tk.Label(inner, text=f"#{len(h)-i} {entry.get('product','?')}",
                            font=FONT_BODY, bg=CARD_BG, fg=TEXT).pack(anchor="w")
                    cap = entry.get("caption", "")[:80]
                    posted = entry.get("posted_at", "-")[:19]
                    tk.Label(inner, text=f"{cap}  — {posted}",
                            font=FONT_SMALL, bg=CARD_BG, fg=TEXT2).pack(anchor="w")
        except Exception as e:
            tk.Label(hist_frame, text=f"加载失败: {e}",
                    font=FONT_SMALL, bg=BG, fg=RED).pack()

    # ── Helpers ─────────────────────────────────────────

    def _get_settings(self):
        try:
            from ins账号自动化 import get_settings as gs
            return gs()
        except Exception:
            return {}

    def _tick(self):
        self._clock.config(text=datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        self.root.after(10000, self._tick)

    def _log(self, msg):
        def do():
            self._log_text.config(state="normal")
            self._log_text.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
            self._log_text.see("end")
            self._log_text.config(state="disabled")
        self.root.after(0, do)

    def _clear_log(self):
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    def _refresh_status(self):
        try:
            from ins账号自动化 import get_queue, analytics_totals
            q = len(get_queue())
            a = analytics_totals()
            posted = a.get("posted", 0)
            generated = a.get("generated", 0)
            errors = a.get("errors", 0)

            if hasattr(self, '_cards'):
                for label, val in [("待发布", q), ("已发布", posted), ("已生成", generated), ("错误", errors)]:
                    if label in self._cards:
                        self._cards[label].config(text=str(val))

            if hasattr(self, '_sidebar_q'):
                self._sidebar_q.config(text=f"队列: {q}")
                self._sidebar_gen.config(text=f"生成: {generated}")

            if errors > 3:
                self._status_dot.itemconfig(self._dot_circle, fill=RED)
                self._status_lbl.config(text="异常", fg=RED)
            elif q == 0 and generated == 0:
                self._status_dot.itemconfig(self._dot_circle, fill=ORANGE)
                self._status_lbl.config(text="待配置", fg=ORANGE)
            else:
                self._status_dot.itemconfig(self._dot_circle, fill=GREEN)
                self._status_lbl.config(text="正常", fg=GREEN)
        except Exception:
            self._status_dot.itemconfig(self._dot_circle, fill=TEXT2)
            self._status_lbl.config(text="离线", fg=TEXT2)

        self._refresh_job = self.root.after(5000, self._refresh_status)

    # ── Task runner ─────────────────────────────────────

    def _set_busy(self, busy):
        self._running_task = busy
        state = "disabled" if busy else "normal"
        for btn in getattr(self, '_task_btns', []):
            try:
                btn.config(state=state)
            except:
                pass

    def _run_task(self, func, *args):
        if self._running_task:
            return
        self._set_busy(True)
        buf = io.StringIO()
        self._log(f"开始: {func.__name__}")

        def worker():
            try:
                with redirect_stdout(buf), redirect_stderr(buf):
                    func(*args)
                output = buf.getvalue().strip()
                for line in output.split("\n"):
                    if line.strip():
                        self._log(line.strip())
                self.root.after(0, lambda: self._show_result(True))
            except Exception as e:
                self._log(f"错误: {e}")
                self.root.after(0, lambda: self._show_result(False, str(e)))
            self.root.after(0, self._refresh_status)
            self.root.after(0, lambda: self._set_busy(False))

            # Refresh tab if queue or history
            if self._active_tab == "queue":
                self.root.after(0, self._refresh_queue_display)

        threading.Thread(target=worker, daemon=True).start()

    def _show_result(self, success, msg=""):
        if success:
            self._log("✓ 完成")
            messagebox.showinfo("完成", "操作完成")
        else:
            self._log(f"✗ 失败: {msg}")
            messagebox.showerror("失败", msg[:200])

    # ── Actions ─────────────────────────────────────────

    def _open_dashboard(self):
        import subprocess
        subprocess.Popen(["streamlit", "run", "app.py"], cwd=str(BASE_DIR), shell=True)
        self._log("Streamlit 仪表盘已启动")

    def _gen_batch(self):
        from ins账号自动化.cli import generate_and_queue
        self._run_task(generate_and_queue, 3)

    def _post_one(self):
        from ins账号自动化.cli import post_from_queue
        self._run_task(post_from_queue, 1)

    def _post_all(self):
        from ins账号自动化 import get_queue
        count = len(get_queue())
        if count == 0:
            messagebox.showinfo("提示", "队列为空")
            return
        from ins账号自动化.cli import post_from_queue
        self._run_task(post_from_queue, count)

    def _clear_queue(self):
        if messagebox.askyesno("确认", "确定要清空发布队列？"):
            try:
                from ins账号自动化 import queue_clear
                queue_clear()
                self._log("队列已清空")
                self._refresh_status()
                if self._active_tab == "queue":
                    self._refresh_queue_display()
            except Exception as e:
                self._log(f"清空失败: {e}")

    def _run_scheduler(self):
        from ins账号自动化.cli import run_scheduler
        self._run_task(run_scheduler)

    def destroy(self):
        if self._refresh_job:
            self.root.after_cancel(self._refresh_job)


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("InsAuto — Instagram AI 自动化控制台")
        self.root.geometry("860x640")
        self.root.configure(bg=BG)
        self.root.minsize(720, 520)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        try:
            ico_path = BASE_DIR / "app_icon.png"
            if ico_path.exists():
                ico = tk.PhotoImage(file=str(ico_path))
                self.root.iconphoto(True, ico)
        except Exception:
            pass

        self._page = None
        self._check_session()

    def _check_session(self):
        session_file = BASE_DIR / "ins账号自动化" / "data" / "ig_session.json"
        if session_file.exists():
            try:
                from ins账号自动化.bot import login
                login()
                from ins账号自动化 import config
                self._show_main(config.IG_USERNAME)
                return
            except Exception:
                session_file.unlink(missing_ok=True)
        self._show_login()

    def _show_login(self):
        self._clear()
        self._page = LoginPage(self.root, self._on_login)

    def _on_login(self, username):
        self._show_main(username)

    def _show_main(self, username):
        self._clear()
        self._page = MainPage(self.root, username, self._logout)

    def _logout(self):
        session_file = BASE_DIR / "ins账号自动化" / "data" / "ig_session.json"
        if session_file.exists():
            try:
                session_file.unlink()
            except:
                pass
        self._show_login()

    def _clear(self):
        if self._page:
            try:
                self._page.destroy()
            except:
                pass
            self._page = None
        for w in self.root.winfo_children():
            w.destroy()

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        self.root.destroy()


if __name__ == "__main__":
    App().run()
