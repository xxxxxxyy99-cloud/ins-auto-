"""InsAuto — AI Instagram Content Automation Dashboard."""

import streamlit as st
import threading
import time
import os
import sys
import random
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from ins账号自动化 import (
    get_queue, queue_post, queue_remove, queue_update_caption, queue_clear, queue_count,
    get_history, add_to_history, clear_history, history_count,
    get_settings, save_settings,
    get_status, set_running,
    analytics_totals, analytics_overview,
    get_recent_activity, get_schedule,
    generate_prompt, generate_image, generate_caption, build_caption,
    save_last_post, next_post_delay,
    increment_generated,
    get_logger,
)
from ins账号自动化.content import (
    ASPECT_RATIOS, DEFAULT_CATEGORIES, CAPTION_STYLES,
    generate_batch,
)

log = get_logger("ui")

# ── Page config ──────────────────────────────────────────

st.set_page_config(
    page_title="InsAuto 控制台",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────

st.markdown("""
<style>
    /* Dark theme base */
    .stApp { background-color: #0d1117; }
    .main .block-container { padding-top: 1rem; }

    /* Cards */
    .metric-card {
        background: linear-gradient(135deg, #161b22, #21262d);
        border: 1px solid #30363d;
        border-radius: 12px;
        padding: 1.2rem 1rem;
        text-align: center;
    }
    .metric-card .number {
        font-size: 2rem;
        font-weight: 700;
        color: #e6edf3;
        line-height: 1.2;
    }
    .metric-card .label {
        font-size: 0.8rem;
        color: #8b949e;
        margin-top: 0.3rem;
    }

    /* Image cards */
    .img-card {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        overflow: hidden;
        margin-bottom: 0.8rem;
    }
    .img-card img {
        width: 100%;
        object-fit: cover;
    }
    .img-card .info {
        padding: 0.6rem 0.8rem;
        font-size: 0.8rem;
        color: #8b949e;
    }

    /* Section titles */
    .section-title {
        font-size: 1.3rem;
        font-weight: 700;
        color: #e6edf3;
        margin: 1rem 0 0.5rem;
    }

    /* Status badges */
    .badge {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .badge-success { background: #23863622; color: #3fb950; border: 1px solid #23863644; }
    .badge-warning { background: #d2992222; color: #d29922; border: 1px solid #d2992244; }
    .badge-error   { background: #f8514922; color: #f85149; border: 1px solid #f8514944; }

    /* Button overrides */
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s;
    }
    .stButton > button:hover { transform: translateY(-1px); }

    /* Form inputs */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea,
    .stSelectbox > div > div {
        border-radius: 8px !important;
    }
</style>
""", unsafe_allow_html=True)

# ── Session State Init ───────────────────────────────────

if "ig_username" not in st.session_state:
    st.session_state.ig_username = ""
if "ig_sessionid" not in st.session_state:
    st.session_state.ig_sessionid = ""
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "automation_thread" not in st.session_state:
    st.session_state.automation_thread = None
if "_page" not in st.session_state:
    st.session_state._page = "dashboard"
if "_delay_cache" not in st.session_state:
    st.session_state._delay_cache = (0, 0.0)
if "_studio_prompt" not in st.session_state:
    st.session_state._studio_prompt = ""
if "_studio_product" not in st.session_state:
    st.session_state._studio_product = ""
if "_gen_history" not in st.session_state:
    st.session_state._gen_history = []  # (path, product, prompt)


# ═══════════════════════════════════════════════════════════
#  LOGIN PAGE
# ═══════════════════════════════════════════════════════════

if not st.session_state.authenticated:
    st.markdown("""
    <div style="text-align:center;padding-top:4rem;">
        <h1 style="font-size:2.5rem;color:#58a6ff;">🎨 InsAuto</h1>
        <p style="color:#8b949e;font-size:1.1rem;">AI 驱动的 Instagram 内容自动化</p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("### 🔐 连接 Instagram")
        st.caption("点击下方按钮，浏览器会自动打开 Instagram 登录页。登录成功后自动检测并返回。")

        col_a, col_b = st.columns(2)
        with col_a:
            login_clicked = st.button("🔗 浏览器登录", use_container_width=True, type="primary")
        with col_b:
            demo = st.button("🎮 离线模式", use_container_width=True)

        if login_clicked:
            st.session_state._login_start_time = time.time()
            from ins账号自动化.bot import SESSION_FILE as _session_file

            def _thread_login():
                try:
                    from ins账号自动化.bot import login as pw_login
                    pw_login(interactive=True)
                except Exception:
                    pass

            t = threading.Thread(target=_thread_login, daemon=True)
            t.start()
            st.session_state._login_started = True
            st.rerun()

        if st.session_state.get("_login_started"):
            from ins账号自动化.bot import SESSION_FILE as _sf
            start_t = st.session_state._login_start_time
            # Check if session file was just written (login succeeded)
            if _sf.exists() and _sf.stat().st_mtime >= start_t:
                st.session_state.ig_username = "instagram_user"
                st.session_state.authenticated = True
                st.session_state._login_started = False
                st.rerun()
            # Timeout after 5 minutes
            elif time.time() - start_t > 300:
                st.error("登录超时（5分钟），请重试。")
                st.session_state._login_started = False
            else:
                elapsed = int(time.time() - start_t)
                with st.spinner(f"浏览器已打开 → 登录 Instagram → 自动检测（{elapsed}秒 / 5分钟）..."):
                    time.sleep(3)
                    st.rerun()

        if demo:
            st.session_state.ig_username = "demo_user"
            st.session_state.ig_sessionid = ""
            st.session_state.authenticated = True
            st.info("💡 离线模式：可以生图和查看队列，但无法发布到 Instagram")
            time.sleep(0.5)
            st.rerun()

    st.stop()


# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════

def _start_auto():
    if st.session_state.automation_thread and st.session_state.automation_thread.is_alive():
        return
    set_running(True)
    from ins账号自动化.state import StateMachine
    StateMachine().set_running(True)

    # Capture values BEFORE starting thread — st.session_state is NOT
    # available from background threads in Streamlit.
    _username = st.session_state.ig_username
    _sessionid = st.session_state.ig_sessionid

    def worker():
        try:
            from ins账号自动化.automation import automation_worker as aw
            aw(_username, _sessionid,
               lambda: not get_status().get("running", False))
        except Exception as e:
            log.error("worker_crash", message=str(e))
            set_running(False)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    st.session_state.automation_thread = t
    log.info("start", message="自动化启动")


def _delay():
    ca, cv = st.session_state._delay_cache
    if time.time() - ca < 60:
        return cv
    s = get_settings()
    v = next_post_delay(int(s.get("interval_days", 2)))
    st.session_state._delay_cache = (time.time(), v)
    return v


def _fmt(iso):
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso)
        n = datetime.now()
        s = (n - d).total_seconds()
        if s < 60: return "刚刚"
        if s < 3600: return f"{int(s//60)}分钟前"
        if s < 86400: return f"{int(s//3600)}小时前"
        return f"{int(s//86400)}天前"
    except:
        return iso[:10]


def _show_image(path, width=280):
    """Display an image from local path."""
    if path and os.path.exists(path):
        st.image(path, width=width)
        return True
    return False


# ═══════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown(f"""
    <div style="text-align:center;padding:0.5rem 0;">
        <span style="font-size:1.5rem;">🎨</span>
        <span style="font-size:1.1rem;font-weight:700;color:#58a6ff;margin-left:0.3rem;">InsAuto</span>
    </div>
    <div style="text-align:center;color:#8b949e;font-size:0.8rem;margin-bottom:0.8rem;">
        @{st.session_state.ig_username}
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    nav_items = [
        ("📊", "仪表盘", "dashboard"),
        ("🎬", "图片工作室", "studio"),
        ("📋", "发布队列", "queue"),
        ("🖼️", "图片库", "gallery"),
        ("📜", "发布历史", "history"),
        ("⚙️", "设置", "settings"),
    ]
    for icon, label, page in nav_items:
        if st.button(f"{icon}  {label}", key=f"nav_{page}",
                     use_container_width=True,
                     type="primary" if st.session_state._page == page else "secondary"):
            st.session_state._page = page
            st.rerun()

    st.divider()

    status = get_status()
    is_run = status.get("running", False)
    sched = get_schedule()
    next_post = sched.get("next_post", "")

    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:0.5rem;padding:0.5rem 0;">
        <span class="badge badge-{'success' if is_run else 'warning'}">{'▶ 运行中' if is_run else '⏸ 已停止'}</span>
    </div>
    """, unsafe_allow_html=True)

    if next_post:
        try:
            dt = datetime.fromisoformat(next_post)
            st.caption(f"⏰ 下次: {dt.strftime('%m-%d %H:%M')}")
        except Exception:
            pass

    if is_run:
        if st.button("⏹ 停止", use_container_width=True):
            set_running(False)
            log.info("stop", message="手动停止")
            st.rerun()
    else:
        if st.button("▶ 启动自动化", use_container_width=True, type="primary"):
            _start_auto()
            st.rerun()

    st.divider()

    if st.button("🚪 断开连接", use_container_width=True):
        set_running(False)
        st.session_state.authenticated = False
        st.rerun()

    st.caption(f"v2.0 · {datetime.now().strftime('%H:%M')}")


# ═══════════════════════════════════════════════════════════
#  PAGE: DASHBOARD
# ═══════════════════════════════════════════════════════════

def page_dashboard():
    st.markdown('<div class="section-title">📊 仪表盘</div>', unsafe_allow_html=True)

    s = get_settings()
    delay_sec = _delay()

    # ── Top row: status bar ──
    cols = st.columns(4)
    info_cards = [
        ("⏰ 下次发布", f"{delay_sec/3600:.1f} 小时", f"间隔 {s.get('interval_days')} 天"),
        ("🎯 主题", s.get('niche', '—')[:20], f"风格: {s.get('style', '—')}"),
        ("🖼️ 图片引擎", s.get('image_model', 'pollinations'), ""),
        ("🧠 文案模型", s.get('llm_model', '—')[:25], ""),
    ]
    for col, (label, value, sub) in zip(cols, info_cards):
        with col:
            st.markdown(f"""
            <div class="metric-card">
                <div class="label">{label}</div>
                <div class="number" style="font-size:1.1rem;">{value}</div>
                <div class="label">{sub}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Stats row ──
    a = analytics_totals()
    c1, c2, c3, c4 = st.columns(4)
    stats = [
        ("🎨", "已生成", a.get("generated", 0), "#3fb950"),
        ("✅", "已发布", a.get("posted", 0), "#58a6ff"),
        ("📋", "队列中", queue_count(), "#d29922"),
        ("⚠️", "错误数", a.get("errors", 0), "#f85149" if a.get("errors", 0) > 0 else "#8b949e"),
    ]
    for col, (icon, label, val, color) in zip([c1, c2, c3, c4], stats):
        with col:
            st.markdown(f"""
            <div class="metric-card">
                <div style="font-size:1.5rem;color:{color};">{icon}</div>
                <div class="number" style="color:{color};">{val}</div>
                <div class="label">{label}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Quick generate ──
    st.markdown("### ⚡ 快捷操作")
    cg1, cg2, cg3, cg4 = st.columns(4)

    with cg1:
        gen_count = st.selectbox("生成数量", [1, 3, 5, 10], index=1, key="qc_count")
    with cg2:
        gen_ratio = st.selectbox("图片比例", list(ASPECT_RATIOS.keys()), index=1, key="qc_ratio")
    with cg3:
        gen_provider = st.selectbox("引擎", ["pollinations", "openrouter"], key="qc_provider")

    with cg4:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🎨 开始生成", type="primary", use_container_width=True, key="gen_btn"):
            with st.spinner(f"正在生成 {gen_count} 张图片..."):
                s = get_settings()
                hashtags_raw = s.get("hashtags", "")
                progress = st.progress(0)
                for i in range(gen_count):
                    try:
                        p, prod = generate_prompt(
                            niche=s.get("niche"),
                            custom_style=s.get("audience", ""),
                        )
                        img = generate_image(p, provider=gen_provider,
                                           model=s.get("image_model") or None,
                                           aspect_ratio=gen_ratio)
                        if img:
                            cap = generate_caption(prod, style=s.get("style"),
                                                   niche=s.get("audience"),
                                                   model=s.get("llm_model", "qwen/qwen-2.5-7b-instruct"),
                                                   instructions=s.get("caption_instructions", ""))
                            if hashtags_raw.strip():
                                cap = build_caption(cap, hashtags_raw.split())
                            queue_post(str(img), cap, prod)
                            increment_generated()
                            st.session_state._gen_history.append((str(img), prod, p))
                            log.info("gen_queued", product=prod, message=f"#{i+1} 生成入队")
                    except Exception as e:
                        st.warning(f"第{i+1}张失败: {e}")
                    progress.progress((i+1) / gen_count)
            st.rerun()

    # ── Queue preview ──
    q = get_queue()
    if q:
        st.markdown(f"### 📋 队列预览（共 {len(q)} 篇）")
        cols = st.columns(min(len(q), 4))
        for i, entry in enumerate(q[:4]):
            with cols[i]:
                cap_preview = entry.get("caption", "")[:60]
                st.markdown(f"""
                <div class="img-card">
                    <div class="info">
                        <strong>#{i+1}</strong> {entry.get('product','?')[:20]}<br>
                        <span style="font-size:0.75rem;">{cap_preview}...</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("📭 队列为空，去「图片工作室」生成一些内容吧！")

    # ── Recent activity ──
    st.markdown("<br>", unsafe_allow_html=True)
    act = get_recent_activity(15)
    if act:
        st.markdown("### 📜 最近动态")
        lines = []
        for e in act[:8]:
            sev = e.get("severity", "info")
            color = "#f85149" if sev == "error" else "#d29922" if sev == "warn" else "#8b949e"
            lines.append(
                f'<span style="color:{color};">●</span> '
                f'<small>{_fmt(e.get("created_at",""))}</small> '
                f'{e.get("event","")} '
                f'<small style="color:#6e7681;">{e.get("message","")[:40]}</small>'
            )
        st.markdown("<br>".join(lines), unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  PAGE: IMAGE STUDIO
# ═══════════════════════════════════════════════════════════

def page_studio():
    st.markdown('<div class="section-title">🎬 图片工作室</div>', unsafe_allow_html=True)
    st.caption("在这里设计 Prompt、预览效果、批量生成图片")

    s = get_settings()

    tab1, tab2, tab3 = st.tabs(["🎯 快速生成", "✏️ 高级编辑", "📦 批量生产"])

    # ── Tab 1: Quick Generate ──
    with tab1:
        col_left, col_right = st.columns([3, 2])

        with col_left:
            st.markdown("#### 生成设置")

            # Category & product
            cat = st.selectbox("产品类别", list(DEFAULT_CATEGORIES.keys()), key="st_cat")
            products = DEFAULT_CATEGORIES.get(cat, DEFAULT_CATEGORIES["kitchen"])
            sel_product = st.selectbox("产品", products, key="st_product")

            # Aspect ratio & count
            c1, c2 = st.columns(2)
            with c1:
                ratio = st.selectbox("比例", list(ASPECT_RATIOS.keys()), index=1, key="st_ratio")
            with c2:
                count = st.number_input("数量", 1, 10, 3, key="st_count")

            # Provider
            provider = st.selectbox(
                "图片引擎",
                ["pollinations", "openrouter"],
                format_func=lambda x: {
                    "pollinations": "Pollinations.ai (免费，快速)",
                    "openrouter": "OpenRouter (高质量，需 API key)",
                }.get(x, x),
                key="st_provider"
            )

            # Custom style prompt
            custom_prompt = st.text_area(
                "自定义提示词（可选，留空则自动生成）",
                placeholder="例如: dark moody lighting, cinematic, bokeh background...",
                key="st_custom"
            )

            st.markdown("<br>", unsafe_allow_html=True)
            gen_btn = st.button("🎨 生成并预览", type="primary", use_container_width=True, key="st_gen_btn")

        with col_right:
            st.markdown("#### 预览")
            preview_placeholder = st.empty()

            if gen_btn:
                with st.spinner("生成中..."):
                    prompt, product = generate_prompt(
                        product=sel_product,
                        niche=s.get("niche"),
                        custom_style=custom_prompt or s.get("audience", ""),
                        category=cat,
                    )

                    st.session_state._studio_prompt = prompt
                    st.session_state._studio_product = product

                    paths = generate_batch(
                        prompt=prompt,
                        count=count,
                        provider=provider,
                        model=s.get("image_model") or "",
                        aspect_ratio=ratio,
                    )

                    if paths:
                        for path in paths:
                            st.session_state._gen_history.append((path, product, prompt))

                        with preview_placeholder:
                            st.success(f"✅ 生成了 {len(paths)} 张图片")
                            st.markdown(f"**Prompt:** {prompt[:200]}...")
                            cols = st.columns(min(len(paths), 3))
                            for i, p in enumerate(paths):
                                with cols[i % 3]:
                                    _show_image(p, width=220)
                                    st.caption(f"#{i+1}")

                        # Add to queue button
                        if st.button("📋 全部加入发布队列", type="primary", use_container_width=True):
                            s2 = get_settings()
                            hashtags_raw = s2.get("hashtags", "")
                            for p in paths:
                                cap = generate_caption(
                                    product, style=s2.get("style"),
                                    niche=s2.get("audience"),
                                    model=s2.get("llm_model", "qwen/qwen-2.5-7b-instruct"),
                                    instructions=s2.get("caption_instructions", ""),
                                )
                                if hashtags_raw.strip():
                                    cap = build_caption(cap, hashtags_raw.split())
                                queue_post(str(p), cap, product)
                                increment_generated()
                            st.success(f"✅ {len(paths)} 条已入队")
                            time.sleep(1)
                            st.rerun()
                    else:
                        with preview_placeholder:
                            st.error("生成失败，请检查网络或切换引擎重试")
            else:
                with preview_placeholder:
                    st.info("👈 设置参数后点击「生成并预览」")

    # ── Tab 2: Advanced Edit ──
    with tab2:
        st.markdown("#### ✏️ 高级 Prompt 编辑")

        col_a, col_b = st.columns([3, 2])

        with col_a:
            # Pre-fill from quick generate
            default_prompt = st.session_state.get("_studio_prompt", "")
            edited_prompt = st.text_area(
                "图片 Prompt",
                value=default_prompt,
                height=120,
                placeholder="详细描述你想生成的图片...",
                key="st_adv_prompt",
                help="越详细越好！描述场景、光线、构图、风格、颜色等"
            )

            st.markdown("**Prompt 技巧：**")
            st.markdown("""
            - 📸 描述场景：flat lay, close-up, lifestyle shot
            - 💡 描述光线：natural light, golden hour, soft diffused light
            - 🎨 描述风格：minimal, rustic, modern, luxury
            - 📐 描述构图：top-down, 45° angle, centered
            - 🔍 描述细节：4K, macro, shallow dof, photorealistic
            """)

        with col_b:
            st.markdown("#### 生成参数")
            adv_ratio = st.selectbox("比例", list(ASPECT_RATIOS.keys()), index=1, key="adv_ratio")
            adv_count = st.number_input("数量", 1, 10, 2, key="adv_count")
            adv_provider = st.selectbox(
                "引擎",
                ["pollinations", "openrouter"],
                format_func=lambda x: {"pollinations": "Pollinations.ai", "openrouter": "OpenRouter"}.get(x, x),
                key="adv_provider",
            )

            if st.button("🚀 用此 Prompt 生成", type="primary", use_container_width=True, key="adv_gen"):
                if edited_prompt.strip():
                    with st.spinner("生成中..."):
                        paths = generate_batch(
                            prompt=edited_prompt.strip(),
                            count=adv_count,
                            provider=adv_provider,
                            model=s.get("image_model") or "",
                            aspect_ratio=adv_ratio,
                        )
                        if paths:
                            st.success(f"✅ {len(paths)} 张已生成")
                            for p in paths:
                                _show_image(p, width=220)
                                st.session_state._gen_history.append((p, "custom", edited_prompt.strip()[:80]))
                        else:
                            st.error("生成失败")
                else:
                    st.warning("请先输入 Prompt")

    # ── Tab 3: Batch Production ──
    with tab3:
        st.markdown("#### 📦 批量生产")

        st.markdown("为多个产品批量生成图片和文案，适合一次性填充发布队列。")

        # Select category
        batch_cat = st.selectbox("选择类别", list(DEFAULT_CATEGORIES.keys()), key="batch_cat")
        all_products = DEFAULT_CATEGORIES.get(batch_cat, DEFAULT_CATEGORIES["kitchen"])

        # Multi-select products
        selected_products = st.multiselect(
            f"选择产品（共 {len(all_products)} 个可选）",
            all_products,
            default=all_products[:5],
            key="batch_products",
        )

        cb1, cb2, cb3 = st.columns(3)
        with cb1:
            batch_ratio = st.selectbox("图片比例", list(ASPECT_RATIOS.keys()), index=1, key="batch_ratio")
        with cb2:
            per_product = st.number_input("每产品张数", 1, 5, 2, key="batch_per")
        with cb3:
            batch_provider = st.selectbox(
                "引擎",
                ["pollinations", "openrouter"],
                format_func=lambda x: {"pollinations": "Pollinations.ai", "openrouter": "OpenRouter"}.get(x, x),
                key="batch_provider",
            )

        total_images = len(selected_products) * per_product
        st.info(f"📊 将生成 **{len(selected_products)}** 个产品 × **{per_product}** 张 = **{total_images}** 张图片")

        if st.button("🏭 启动批量生产", type="primary", use_container_width=True, key="batch_start"):
            if not selected_products:
                st.warning("请选择至少一个产品")
                return

            progress_bar = st.progress(0)
            status_text = st.empty()
            total = len(selected_products)
            completed = 0

            s_batch = get_settings()
            hashtags_raw = s_batch.get("hashtags", "")

            for pi, product in enumerate(selected_products):
                status_text.text(f"正在处理: {product} ({pi+1}/{total})")
                for img_i in range(per_product):
                    try:
                        prompt, _ = generate_prompt(product=product, niche=s_batch.get("niche"))
                        img_path = generate_image(
                            prompt, provider=batch_provider,
                            model=s_batch.get("image_model") or "",
                            aspect_ratio=batch_ratio,
                        )
                        if img_path:
                            cap = generate_caption(
                                product, style=s_batch.get("style"),
                                niche=s_batch.get("audience"),
                                model=s_batch.get("llm_model", "qwen/qwen-2.5-7b-instruct"),
                                instructions=s_batch.get("caption_instructions", ""),
                            )
                            if hashtags_raw.strip():
                                cap = build_caption(cap, hashtags_raw.split())
                            queue_post(str(img_path), cap, product)
                            increment_generated()
                            completed += 1
                    except Exception as e:
                        st.warning(f"{product} 第{img_i+1}张失败: {e}")
                progress_bar.progress((pi+1) / total)

            status_text.text(f"✅ 完成！共生成 {completed}/{total_images} 张，已加入队列")
            st.balloons()


# ═══════════════════════════════════════════════════════════
#  PAGE: QUEUE
# ═══════════════════════════════════════════════════════════

def page_queue():
    st.markdown('<div class="section-title">📋 发布队列</div>', unsafe_allow_html=True)

    q = get_queue()
    if not q:
        st.info("📭 队列为空，去「图片工作室」生成内容吧！")
        if st.button("🎨 去图片工作室", type="primary"):
            st.session_state._page = "studio"
            st.rerun()
        return

    st.caption(f"共 {len(q)} 篇待发布")

    # Bulk actions
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🗑️ 清空队列", use_container_width=True):
            queue_clear()
            log.info("queue_cleared", message="队列已清空")
            st.rerun()
    with c2:
        if st.button("📤 立即发布全部", type="primary", use_container_width=True,
                     disabled=not st.session_state.ig_sessionid):
            with st.spinner("发布中..."):
                from ins账号自动化.cli import post_from_queue
                post_from_queue(len(q))
            st.rerun()

    st.divider()

    for i, entry in enumerate(q):
        img_path = entry.get("image_path", "")
        product = entry.get("product", "?")
        caption = entry.get("caption", "")

        with st.container():
            col_img, col_text, col_actions = st.columns([1, 3, 1])

            with col_img:
                if img_path and os.path.exists(img_path):
                    st.image(img_path, width=160)

            with col_text:
                st.markdown(f"**#{i+1} · {product}**")
                nc = st.text_area(
                    "文案", value=caption, key=f"qcap_{i}",
                    height=90, label_visibility="collapsed"
                )
                if nc != caption:
                    queue_update_caption(i, nc)
                    st.rerun()
                st.caption(f"📁 {Path(img_path).name}" if img_path else "无图片")

            with col_actions:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🗑️ 删除", key=f"qdel_{i}", use_container_width=True):
                    queue_remove(i)
                    st.rerun()
                if st.button("📤 发布", key=f"qpub_{i}", use_container_width=True,
                            disabled=not st.session_state.ig_sessionid):
                    from ins账号自动化.bot import login, post_photo
                    try:
                        cl = login(st.session_state.ig_username, st.session_state.ig_sessionid)
                        if post_photo(img_path, nc):
                            from ins账号自动化 import db
                            db.queue_mark_posted(entry.get("id", 0))
                            db.history_add(img_path, nc, product)
                            db.analytics_increment("posts")
                            log.info("manual_post", product=product, message="手动发布成功")
                            st.success("✅ 已发布")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("发布失败")
                    except Exception as e:
                        st.error(f"错误: {e}")

            st.divider()


# ═══════════════════════════════════════════════════════════
#  PAGE: GALLERY
# ═══════════════════════════════════════════════════════════

def page_gallery():
    st.markdown('<div class="section-title">🖼️ 图片库</div>', unsafe_allow_html=True)

    from ins账号自动化.content import IMAGE_DIR
    images = sorted(IMAGE_DIR.glob("*.jpg"), key=os.path.getmtime, reverse=True)

    if not images:
        st.info("还没有生成的图片")
        return

    st.caption(f"共 {len(images)} 张图片")

    # Grid view
    cols = st.columns(4)
    for i, img_path in enumerate(images[:40]):
        with cols[i % 4]:
            st.image(str(img_path), width=180)
            mtime = datetime.fromtimestamp(os.path.getmtime(img_path))
            st.caption(f"{mtime.strftime('%m-%d %H:%M')}")

    # Cleanup
    if len(images) > 50:
        st.warning(f"图片已达 {len(images)} 张，建议清理")
        if st.button("🧹 清理最早的 20 张"):
            for old in sorted(images, key=os.path.getmtime)[:20]:
                try:
                    os.remove(old)
                except:
                    pass
            st.rerun()


# ═══════════════════════════════════════════════════════════
#  PAGE: HISTORY
# ═══════════════════════════════════════════════════════════

def page_history():
    st.markdown('<div class="section-title">📜 发布历史</div>', unsafe_allow_html=True)

    h = get_history()
    if not h:
        st.info("暂无发布记录")
        return

    st.caption(f"共 {len(h)} 篇已发布")

    if st.button("🗑️ 清空历史"):
        clear_history()
        st.rerun()

    st.divider()

    for i, entry in enumerate(reversed(h[-50:])):
        with st.container():
            c1, c2 = st.columns([1, 4])
            with c1:
                img_path = entry.get("image_path", "")
                if img_path and os.path.exists(img_path):
                    st.image(img_path, width=140)
                else:
                    st.markdown("📷 *无预览*")
            with c2:
                product = entry.get("product", "?")
                caption = entry.get("caption", "")[:120]
                posted = _fmt(entry.get("posted_at", ""))
                st.markdown(f"**#{len(h)-i} · {product}**  _{posted}_")
                st.caption(caption)
        st.divider()


# ═══════════════════════════════════════════════════════════
#  PAGE: SETTINGS
# ═══════════════════════════════════════════════════════════

def page_settings():
    st.markdown('<div class="section-title">⚙️ 设置</div>', unsafe_allow_html=True)

    s = get_settings()

    tab1, tab2, tab3 = st.tabs(["📝 基础设置", "🤖 AI 模型", "🏷️ 标签 & 自定义"])

    with tab1:
        col_a, col_b = st.columns(2)
        with col_a:
            interval = st.number_input("⏰ 发布间隔（天）", 1, 14,
                                      int(s.get("interval_days", 2)))
            niche = st.text_input("🎯 内容主题", s.get("niche", ""),
                                  placeholder="例如: 现代厨房、家居好物、健身生活")
            audience = st.text_input("👥 目标受众", s.get("audience", ""),
                                     placeholder="home cooks, juice lovers...")
        with col_b:
            style_opts = ["casual", "luxury", "fitness", "minimal", "educational", "sale"]
            style_labels = {"casual": "日常轻松", "luxury": "高端奢华", "fitness": "运动活力",
                          "minimal": "极简主义", "educational": "知识教学", "sale": "促销转化"}
            v = s.get("style", "casual")
            idx = style_opts.index(v) if v in style_opts else 0
            style = st.selectbox("✍️ 文案风格", style_opts, idx,
                               format_func=lambda x: style_labels.get(x, x))
            hashtags = st.text_area("🏷️ 标签（空格分隔）", s.get("hashtags", ""), height=80)

    with tab2:
        col_c, col_d = st.columns(2)
        with col_c:
            llm_model = st.text_input("🧠 文案模型", s.get("llm_model", "qwen/qwen-2.5-7b-instruct"),
                                     help="OpenRouter 模型 ID，如 qwen/qwen-2.5-7b-instruct")
            llm_options = [
                "qwen/qwen-2.5-7b-instruct",
                "openai/gpt-4o-mini",
                "anthropic/claude-3.5-haiku",
                "google/gemini-2.0-flash-001",
                "meta-llama/llama-4-maverick",
            ]
            st.caption("💡 推荐模型：")
            for opt in llm_options:
                if st.button(f"  {opt}", key=f"llm_{opt[:20]}"):
                    llm_model = opt
                    save_settings(llm_model=opt)

        with col_d:
            image_model = st.text_input("🖼️ 图片模型", s.get("image_model", "pollinations"),
                                       help="pollinations（免费）/ openai/dall-e-3（付费高质量）")
            img_options = [
                ("pollinations", "Pollinations.ai (免费)"),
                ("openai/dall-e-3", "DALL-E 3 (高质量)"),
                ("google/imagen-4.0-generate-001", "Imagen 4"),
            ]
            st.caption("💡 图片引擎：")
            for val, label in img_options:
                if st.button(f"  {label}", key=f"img_{val[:15]}"):
                    image_model = val
                    save_settings(image_model=val)

    with tab3:
        caption_instructions = st.text_area(
            "📝 文案自定义指令",
            s.get("caption_instructions", ""),
            height=80,
            placeholder="例如: 每句话都要以 emoji 结尾 / 用第二人称 / 不要太营销..."
        )

    if st.button("💾 保存设置", type="primary", use_container_width=True):
        save_settings(
            interval_days=interval, niche=niche, style=style, audience=audience,
            llm_model=llm_model, image_model=image_model,
            hashtags=hashtags, caption_instructions=caption_instructions,
        )
        log.info("settings_saved",
                 message=f"间隔={interval}d 风格={style} 图片={image_model}")
        st.success("✅ 设置已保存")
        time.sleep(0.5)
        st.rerun()

    st.divider()
    st.caption(f"当前配置: 文案 {s.get('llm_model')} · 图片 {s.get('image_model')} · SQLite")


# ═══════════════════════════════════════════════════════════
#  AUTO-START: if worker was running before, resume it
# ═══════════════════════════════════════════════════════════

if "_auto_started" not in st.session_state:
    st.session_state._auto_started = False

if not st.session_state._auto_started and not st.session_state.get("automation_thread"):
    status = get_status()
    if status.get("running"):
        # State says running but no thread → crash recovery, auto-restart
        log.info("auto_restart", message="检测到之前运行中，自动恢复")
        _start_auto()
    st.session_state._auto_started = True


# ═══════════════════════════════════════════════════════════
#  ROUTER
# ═══════════════════════════════════════════════════════════

page = st.session_state._page
page_funcs = {
    "dashboard": page_dashboard,
    "studio": page_studio,
    "queue": page_queue,
    "gallery": page_gallery,
    "history": page_history,
    "settings": page_settings,
}
page_funcs.get(page, page_dashboard)()
