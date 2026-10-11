"""InsAuto — Instagram AI Content Operations Assistant."""

import streamlit as st
import time
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
    asset_add, asset_get_all, asset_toggle_favorite, asset_delete,
    asset_count, asset_get_by_category,
    draft_save, draft_get_all, draft_get, draft_update, draft_delete,
    draft_mark_posted, draft_count,
    draft_submit_review, draft_approve, draft_reject, review_count,
    draft_search,
    get_history, add_to_history, clear_history, history_count,
    get_settings, save_settings,
    analytics_totals, analytics_overview, analytics_increment,
    get_recent_activity, init_db, log_event,
    generate_prompt, generate_image, generate_caption, generate_hashtags,
    build_caption, generate_batch,
    ASPECT_RATIOS, DEFAULT_CATEGORIES, CAPTION_STYLES, TOPICS, TOPIC_KEYS,
    IMAGE_DIR,
    login as bot_login, post_photo, SESSION_FILE,
    get_logger,
)

from ins账号自动化.config import GEMINI_API_KEY, OPENROUTER_API_KEY

log = get_logger("ui")

# ── Page config ────────────────────────────────────────────────

st.set_page_config(
    page_title="InsAuto 内容助手",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS (dark theme) ────────────────────────────────────

st.markdown("""
<style>
    .stApp { background-color: #0d1117; }
    .main .block-container { padding-top: 1rem; }

    .metric-card {
        background: linear-gradient(135deg, #161b22, #21262d);
        border: 1px solid #30363d; border-radius: 12px;
        padding: 1.2rem 1rem; text-align: center;
    }
    .metric-card .number { font-size: 2rem; font-weight: 700; color: #e6edf3; line-height: 1.2; }
    .metric-card .label { font-size: 0.8rem; color: #8b949e; margin-top: 0.3rem; }

    .img-card {
        background: #161b22; border: 1px solid #30363d;
        border-radius: 10px; overflow: hidden; margin-bottom: 0.8rem;
    }
    .img-card img { width: 100%; object-fit: cover; }
    .img-card .info { padding: 0.6rem 0.8rem; font-size: 0.8rem; color: #8b949e; }

    .section-title { font-size: 1.3rem; font-weight: 700; color: #e6edf3; margin: 1rem 0 0.5rem; }

    .badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 20px; font-size: 0.75rem; font-weight: 600; }
    .badge-success { background: #23863622; color: #3fb950; border: 1px solid #23863644; }
    .badge-warning { background: #d2992222; color: #d29922; border: 1px solid #d2992244; }
    .badge-error   { background: #f8514922; color: #f85149; border: 1px solid #f8514944; }
    .badge-info    { background: #58a6ff22; color: #58a6ff; border: 1px solid #58a6ff44; }

    .stButton > button { border-radius: 8px; font-weight: 600; transition: all 0.2s; }
    .stButton > button:hover { transform: translateY(-1px); }

    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea,
    .stSelectbox > div > div { border-radius: 8px !important; }

    /* Phone preview frame */
    .phone-frame {
        background: #000; border: 3px solid #30363d; border-radius: 24px;
        padding: 8px; max-width: 320px; margin: 0 auto;
    }
    .phone-frame img { border-radius: 12px; width: 100%; }
    .phone-frame .caption-text { color: #e6edf3; font-size: 0.85rem; padding: 8px 4px;
        white-space: pre-wrap; word-break: break-word; line-height: 1.4; }
</style>
""", unsafe_allow_html=True)

# ── Session State Init ─────────────────────────────────────────

DEFAULTS = {
    "authenticated": False,
    "_page": "dashboard",
    "_studio_prompt": "",
    "_studio_product": "",
    "_studio_image": "",
    "_studio_caption": "",
    "_studio_hashtags": "",
    "_gen_history": [],
    "_login_start_time": 0.0,
    "_login_pending": False,
}

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def _fmt_ts(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).strftime("%m-%d %H:%M")
    except Exception:
        return ts[:16] if ts else ""


def _show_image(path: str, caption: str = "", width: int = 280):
    """Display an image from a local path."""
    if path and Path(path).exists():
        st.image(str(path), caption=caption, width=width)


def _badge(status: str) -> str:
    m = {"draft": "badge-warning", "ready": "badge-info", "posted": "badge-success"}
    return f'<span class="badge {m.get(status, "badge-warning")}">{status}</span>'


def _ensure_login():
    """Check if Instagram session file exists and is valid."""
    if st.session_state.authenticated:
        return True
    if SESSION_FILE.exists():
        # Session file exists → user has logged in before
        st.session_state.authenticated = True
        return True
    return False


def _clear_studio():
    for k in ("_studio_prompt", "_studio_product", "_studio_image",
              "_studio_caption", "_studio_hashtags"):
        st.session_state[k] = ""
    for k in ("edit_caption", "edit_hashtags",
              "edit_upload_caption", "edit_upload_hashtags", "tag_output"):
        st.session_state.pop(k, None)


def _publish_caption(cap: str, tags: str) -> str:
    """Final caption text: deduped, limited hashtag block appended."""
    try:
        limit = int(get_settings().get("publish_hashtag_limit", "15") or 15)
    except (TypeError, ValueError):
        limit = 15
    return build_caption(cap, tags.split() if tags else None, limit=limit)


def _post_failed(product: str, why: str = "Instagram 页面未完成发布"):
    """Uniform failure bookkeeping: activity log + error counter + notice."""
    log_event("post_failed", product=product, message=why, severity="error")
    analytics_increment("errors")
    st.error(f"❌ 发布失败：{why}。若为登录过期，请点侧边栏「🔌」断开后重新登录，再试一次。")


# ═══════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 🎨 InsAuto")
    st.caption("Instagram AI 内容运营助手")

    # ── Login ──
    if not st.session_state.authenticated:
        st.markdown("---")
        st.markdown("### 🔐 Instagram")
        c1, c2 = st.columns(2)

        with c1:
            if st.button("🔗 登录", use_container_width=True, type="primary"):
                st.session_state._login_start_time = time.time()
                st.session_state._login_pending = True
                st.rerun()

        # Two-step login: show info first, then block
        if st.session_state.get("_login_pending"):
            st.info("浏览器已打开，请在浏览器中登录 Instagram。登录成功后自动返回。")
            try:
                bot_login(interactive=True)
                st.session_state.authenticated = True
            except Exception as e:
                st.error(f"登录失败: {e}")
            st.session_state._login_pending = False
            st.session_state._login_start_time = 0
            st.rerun()

        with c2:
            if st.button("🎮 离线", use_container_width=True):
                st.session_state.authenticated = True
                st.rerun()

        # Detect login completion from browser login (polling fallback)
        if st.session_state._login_start_time > 0 and SESSION_FILE.exists():
            mtime = SESSION_FILE.stat().st_mtime
            if mtime >= st.session_state._login_start_time:
                st.session_state.authenticated = True
                st.session_state._login_start_time = 0
                st.rerun()

    else:
        col_a, col_b = st.columns([3, 1])
        with col_a:
            st.success("✅ 已连接 Instagram")
        with col_b:
            if st.button("🔌", help="断开连接"):
                SESSION_FILE.unlink(missing_ok=True)
                st.session_state.authenticated = False
                st.rerun()

    # ── Navigation ──
    st.markdown("---")
    st.markdown("### 📋 导航")

    pages = {
        "dashboard": "📊 Dashboard",
        "studio":   "✏️ 内容工作室",
        "drafts":   "📋 草稿箱",
        "review":   "",  # dynamic label — see below
        "assets":   "📁 素材库",
        "content":  "📂 内容管理",
        "history":  "📝 发布记录",
        "analytics": "📈 数据统计",
        "settings": "⚙️ 设置",
    }

    for key, label in pages.items():
        if not label:
            # Dynamic label: review count
            rc = review_count()
            label = f"🔍 审核中心  🔴{rc}" if rc > 0 else "🔍 审核中心"
        if st.button(label, key=f"nav_{key}", use_container_width=True,
                     type="primary" if st.session_state._page == key else "secondary"):
            st.session_state._page = key
            st.rerun()

    st.markdown("---")
    st.caption(f"v2.1 · {datetime.now().strftime('%Y-%m-%d')}")


# ═══════════════════════════════════════════════════════════════
#  PAGE: DASHBOARD
# ═══════════════════════════════════════════════════════════════

if st.session_state._page == "dashboard":
    st.markdown('<p class="section-title">📊 Dashboard</p>', unsafe_allow_html=True)

    totals = analytics_totals()
    overview_7 = analytics_overview(7)
    overview_30 = analytics_overview(30)

    # ── Metric Cards ──
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.markdown(f"""<div class="metric-card">
            <div class="number">{totals.get('generated', 0)}</div>
            <div class="label">📊 总内容数</div></div>""", unsafe_allow_html=True)
    with col_m2:
        st.markdown(f"""<div class="metric-card">
            <div class="number">{totals.get('posts', 0)}</div>
            <div class="label">🚀 已发布数</div></div>""", unsafe_allow_html=True)
    with col_m3:
        total_drafts = draft_count("draft") + review_count()
        st.markdown(f"""<div class="metric-card">
            <div class="number">{total_drafts}</div>
            <div class="label">📋 草稿数</div></div>""", unsafe_allow_html=True)
    with col_m4:
        st.markdown(f"""<div class="metric-card">
            <div class="number">{totals.get('errors', 0)}</div>
            <div class="label">❌ 失败数</div></div>""", unsafe_allow_html=True)

    # ── Quick Actions ──
    st.markdown("---")
    col_a1, col_a2, col_a3, col_a4 = st.columns(4)
    with col_a1:
        if st.button("✏️ 创建内容", use_container_width=True, type="primary"):
            st.session_state._page = "studio"
            st.rerun()
    with col_a2:
        if st.button("📋 查看草稿", use_container_width=True):
            st.session_state._page = "drafts"
            st.rerun()
    with col_a3:
        if st.button("🔍 审核中心", use_container_width=True):
            st.session_state._page = "review"
            st.rerun()
    with col_a4:
        if st.button("📂 内容管理", use_container_width=True):
            st.session_state._page = "content"
            st.rerun()

    st.markdown("---")

    # ── Charts: 7-day + 30-day side by side ──
    col_c1, col_c2 = st.columns(2)

    with col_c1:
        st.markdown("#### 📈 最近7天发布")
        if overview_7:
            chart_7 = []
            for r in reversed(overview_7):
                chart_7.append({
                    "日期": r["date"][5:],
                    "发布": r["posts"],
                    "生成": r["generated"],
                })
            st.bar_chart(chart_7, x="日期", y=["生成", "发布"], height=280)
        else:
            st.caption("暂无数据")

    with col_c2:
        st.markdown("#### 📈 最近30天趋势")
        if overview_30:
            chart_30 = []
            for r in reversed(overview_30):
                chart_30.append({
                    "日期": r["date"][5:],
                    "发布": r["posts"],
                    "生成": r["generated"],
                })
            st.line_chart(chart_30, x="日期", y=["生成", "发布"], height=280)
        else:
            st.caption("暂无数据")

    # ── Content Status Breakdown ──
    st.markdown("---")
    st.markdown("#### 📊 内容状态分布")

    posted_count = draft_count("posted")
    draft_only = draft_count("draft")
    in_review = review_count()

    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    with col_s1:
        st.markdown(f"""<div class="metric-card">
            <div class="number">{draft_only}</div>
            <div class="label"><span class="badge badge-warning">草稿</span></div></div>""",
                   unsafe_allow_html=True)
    with col_s2:
        st.markdown(f"""<div class="metric-card">
            <div class="number">{in_review}</div>
            <div class="label"><span class="badge badge-info">审核中</span></div></div>""",
                   unsafe_allow_html=True)
    with col_s3:
        st.markdown(f"""<div class="metric-card">
            <div class="number">{posted_count}</div>
            <div class="label"><span class="badge badge-success">已发布</span></div></div>""",
                   unsafe_allow_html=True)
    with col_s4:
        st.markdown(f"""<div class="metric-card">
            <div class="number">{asset_count()}</div>
            <div class="label">📁 素材资产</div></div>""",
                   unsafe_allow_html=True)

    # ── Recent Activity ──
    st.markdown("---")
    st.markdown("#### 🕐 最近活动")
    acts = get_recent_activity(10)
    if acts:
        for a in acts:
            sev = a.get("severity", "info")
            icon = {"info": "ℹ️", "warn": "⚠️", "error": "❌"}.get(sev, "ℹ️")
            msg = a.get("message", "") or ""
            evt = a.get("event", "")
            product = a.get("product", "")
            if product:
                evt = f"{evt} ({product})"
            st.caption(f"{icon} {_fmt_ts(a['created_at'])} — **{evt}**: {msg}")
    else:
        st.caption("还没有活动记录。开始创建内容吧！")


# ═══════════════════════════════════════════════════════════════
#  PAGE: STUDIO (内容工作室)
# ═══════════════════════════════════════════════════════════════

elif st.session_state._page == "studio":
    st.markdown('<p class="section-title">✏️ 内容工作室</p>', unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs(["🎯 快速生成", "📷 图片上传", "🏷️ 标签工具", "📦 批量生产"])

    # ── Tab 1: Quick Generate ──
    with tab1:
        col_left, col_right = st.columns([1, 1])

        with col_left:
            st.markdown("#### ⚙️ 生成设置")

            category = st.selectbox("产品品类", list(DEFAULT_CATEGORIES.keys()),
                                     key="studio_cat")
            product_idx = st.selectbox("具体产品", list(range(len(DEFAULT_CATEGORIES[category]))),
                                       format_func=lambda i: DEFAULT_CATEGORIES[category][i],
                                       key="studio_prod_idx")
            product = DEFAULT_CATEGORIES[category][product_idx]

            col_a, col_b = st.columns(2)
            with col_a:
                topic_sel = st.selectbox("内容主题", ["无"] + TOPIC_KEYS,
                                         key="studio_topic",
                                         format_func=lambda t: f"{t} — {TOPICS[t][:30]}..." if t != "无" else "无特定主题")
            with col_b:
                style = st.selectbox("文案风格", list(CAPTION_STYLES.keys()), key="studio_style")

            nic = st.text_input("目标受众", get_settings().get("audience", ""), key="studio_nic")

            st.markdown("#### 🖼️ 图片设置")
            ar = st.selectbox("比例", list(ASPECT_RATIOS.keys()), index=0, key="studio_ar")
            _img_opts = ["gemini", "pollinations", "openrouter"]
            _saved_img = get_settings().get("image_model", "gemini")
            img_model = st.selectbox("图片模型", _img_opts,
                                     index=_img_opts.index(_saved_img) if _saved_img in _img_opts else 0,
                                     key="studio_img_model")

            gen_btn = st.button("🎲 生成内容", use_container_width=True, type="primary")
            if st.button("🧹 清空预览", use_container_width=True):
                _clear_studio()
                st.rerun()

            if gen_btn:
                with st.spinner("生成中..."):
                    prompt, product_name = generate_prompt(product=product, niche=nic)
                    st.session_state._studio_prompt = prompt
                    st.session_state._studio_product = product_name

                    img_path = generate_image(prompt, provider=img_model,
                                              model=None,
                                              aspect_ratio=ASPECT_RATIOS[ar])
                    st.session_state._studio_image = img_path

                    caption = generate_caption(product_name, style=style, niche=nic,
                                               model=get_settings().get("llm_model", "qwen/qwen-2.5-7b-instruct"),
                                               instructions=get_settings().get("caption_instructions", ""))
                    st.session_state._studio_caption = caption

                    # Auto-generate hashtags
                    try:
                        tags = generate_hashtags(product_name, niche=nic)
                    except Exception:
                        tags = get_settings().get("hashtags", "")
                    st.session_state._studio_hashtags = tags

                    # Keep the editable preview widgets in sync with the new content
                    st.session_state["edit_caption"] = caption
                    st.session_state["edit_hashtags"] = tags

                    # Save to assets
                    if img_path:
                        asset_add(img_path, product=product_name, category=category,
                                  prompt=prompt, model=img_model, tags=tags)
                        analytics_increment("generated")
                    else:
                        st.error("❌ 图片生成失败：所有引擎都不可用。请检查网络，或配置 GEMINI_API_KEY / OpenRouter 余额。")

                    st.session_state._gen_history.append((img_path, product_name, prompt))

        with col_right:
            st.markdown("#### 👁️ 预览")

            if st.session_state._studio_image:
                _show_image(st.session_state._studio_image, st.session_state._studio_product)
                st.caption(f"**Prompt:** {st.session_state._studio_prompt[:200]}...")

                with st.expander("📝 文案", expanded=True):
                    st.text_area("Caption", st.session_state._studio_caption, height=120, key="edit_caption")
                    st.text_input("Hashtags", st.session_state._studio_hashtags, key="edit_hashtags")

                col_save, col_review, col_post = st.columns(3)
                with col_save:
                    if st.button("💾 保存草稿", use_container_width=True):
                        final_cap = st.session_state.get("edit_caption", st.session_state._studio_caption)
                        final_tags = st.session_state.get("edit_hashtags", st.session_state._studio_hashtags)
                        cur_topic = topic_sel if topic_sel != "无" else ""
                        draft_save(
                            image_path=st.session_state._studio_image,
                            caption=final_cap,
                            hashtags=final_tags,
                            product=st.session_state._studio_product,
                            category=category,
                            topic=cur_topic,
                        )
                        log_event("draft_saved", product=st.session_state._studio_product,
                                  message="草稿已保存")
                        st.success("草稿已保存!")
                        st.rerun()

                with col_review:
                    if st.button("🔍 提交审核", use_container_width=True):
                        final_cap = st.session_state.get("edit_caption", st.session_state._studio_caption)
                        final_tags = st.session_state.get("edit_hashtags", st.session_state._studio_hashtags)
                        cur_topic = topic_sel if topic_sel != "无" else ""
                        did = draft_save(
                            image_path=st.session_state._studio_image,
                            caption=final_cap,
                            hashtags=final_tags,
                            product=st.session_state._studio_product,
                            category=category,
                            topic=cur_topic,
                        )
                        draft_submit_review(did)
                        log_event("review_submitted", product=st.session_state._studio_product,
                                  message="已提交审核")
                        st.success("已提交审核!")
                        st.rerun()

                with col_post:
                    if st.button("🚀 发布到 Instagram", use_container_width=True, type="primary"):
                        if _ensure_login():
                            final_cap = st.session_state.get("edit_caption", st.session_state._studio_caption)
                            final_tags = st.session_state.get("edit_hashtags", st.session_state._studio_hashtags)
                            full_caption = _publish_caption(final_cap, final_tags)
                            with st.spinner("发布中..."):
                                ok = post_photo(st.session_state._studio_image, full_caption)
                            if ok:
                                add_to_history(st.session_state._studio_image, full_caption,
                                               st.session_state._studio_product)
                                analytics_increment("posts")
                                did = draft_save(st.session_state._studio_image, final_cap, final_tags,
                                                 st.session_state._studio_product, category,
                                                 topic_sel if topic_sel != "无" else "")
                                draft_mark_posted(did)
                                log_event("post_success", product=st.session_state._studio_product,
                                          message="手动发布成功")
                                st.success("✅ 发布成功！")
                            else:
                                _post_failed(st.session_state._studio_product)
                        else:
                            st.warning("⚠️ 请先在侧边栏登录 Instagram。")
            else:
                st.info("点击「生成内容」创建你的第一条内容。")

    # ── Tab 2: Image Upload ──
    with tab2:
        st.markdown("#### 📷 上传你的图片")

        col_up_left, col_up_right = st.columns([1, 1])

        with col_up_left:
            uploaded_file = st.file_uploader(
                "选择图片", type=["jpg", "jpeg", "png", "webp"],
                key="studio_upload", help="支持 JPG / PNG / WebP"
            )

            if uploaded_file is not None:
                # Save uploaded file to generated_images
                import hashlib as _hl
                upload_bytes = uploaded_file.read()
                fhash = _hl.md5(upload_bytes).hexdigest()[:12]
                ext = Path(uploaded_file.name).suffix or ".jpg"
                upload_path = IMAGE_DIR / f"upload_{fhash}{ext}"
                if not upload_path.exists():
                    upload_path.write_bytes(upload_bytes)
                st.session_state._studio_image = str(upload_path)
                st.success(f"✅ 已上传: {uploaded_file.name}")

            # Content context for AI generation
            st.markdown("#### 📝 内容描述")
            upload_product = st.text_input(
                "产品/主题", key="upload_product",
                placeholder="例如: handmade ceramic mug, sunset beach photo...",
                help="描述图片内容，AI 据此生成文案和标签"
            )
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                upload_topic = st.selectbox(
                    "内容主题", ["无"] + TOPIC_KEYS, key="upload_topic",
                    format_func=lambda t: f"{t} — {TOPICS[t][:25]}..." if t != "无" else "无特定主题"
                )
            with col_t2:
                upload_style = st.selectbox(
                    "文案风格", list(CAPTION_STYLES.keys()), key="upload_style"
                )

            gen_upload_btn = st.button(
                "✨ 生成文案和标签", key="gen_upload_btn",
                use_container_width=True, type="primary",
                disabled=not st.session_state._studio_image
            )

            if gen_upload_btn and st.session_state._studio_image:
                with st.spinner("AI 分析中..."):
                    prod = upload_product or "product"
                    # Generate caption
                    cap = generate_caption(
                        prod, style=upload_style,
                        niche=get_settings().get("audience", ""),
                        model=get_settings().get("llm_model", "qwen/qwen-2.5-7b-instruct"),
                        instructions=get_settings().get("caption_instructions", ""),
                    )
                    st.session_state._studio_caption = cap
                    # Generate hashtags
                    tags = generate_hashtags(prod, niche=get_settings().get("audience", ""))
                    st.session_state._studio_hashtags = tags
                    st.session_state._studio_product = prod
                    st.session_state["edit_upload_caption"] = cap
                    st.session_state["edit_upload_hashtags"] = tags

                    # Save to assets
                    asset_add(
                        st.session_state._studio_image,
                        product=prod,
                        category="upload",
                        tags=tags,
                    )
                    analytics_increment("generated")
                    log_event("upload_processed", product=prod, message="用户上传图片并生成内容")
                st.success("内容已生成")
                st.rerun()

        with col_up_right:
            st.markdown("#### 👁️ 预览")
            if st.session_state._studio_image:
                _show_image(st.session_state._studio_image, st.session_state.get("_studio_product", ""))
                st.caption(f"📁 {Path(st.session_state._studio_image).name}")

                if st.session_state._studio_caption:
                    with st.expander("📝 文案", expanded=True):
                        st.text_area(
                            "Caption", st.session_state._studio_caption,
                            height=100, key="edit_upload_caption"
                        )
                    with st.expander("🏷️ 标签", expanded=True):
                        st.text_input(
                            "Hashtags", st.session_state._studio_hashtags,
                            key="edit_upload_hashtags"
                        )

                    col_s, col_r, col_p = st.columns(3)
                    with col_s:
                        if st.button("💾 保存草稿", key="upload_save", use_container_width=True):
                            final_cap = st.session_state.get("edit_upload_caption", st.session_state._studio_caption)
                            final_tags = st.session_state.get("edit_upload_hashtags", st.session_state._studio_hashtags)
                            draft_save(
                                image_path=st.session_state._studio_image,
                                caption=final_cap,
                                hashtags=final_tags,
                                product=st.session_state._studio_product,
                                topic=upload_topic if upload_topic != "无" else "",
                            )
                            log_event("draft_saved", product=st.session_state._studio_product,
                                      message="从图片上传保存草稿")
                            st.success("草稿已保存!")

                    with col_r:
                        if st.button("🔍 提交审核", key="upload_review", use_container_width=True):
                            final_cap = st.session_state.get("edit_upload_caption", st.session_state._studio_caption)
                            final_tags = st.session_state.get("edit_upload_hashtags", st.session_state._studio_hashtags)
                            cur_topic = upload_topic if upload_topic != "无" else ""
                            did = draft_save(
                                image_path=st.session_state._studio_image,
                                caption=final_cap,
                                hashtags=final_tags,
                                product=st.session_state._studio_product,
                                topic=cur_topic,
                            )
                            draft_submit_review(did)
                            log_event("review_submitted", product=st.session_state._studio_product,
                                      message="从图片上传提交审核")
                            st.success("已提交审核!")

                    with col_p:
                        if st.button("🚀 发布", key="upload_post", use_container_width=True, type="primary"):
                            if _ensure_login():
                                final_cap = st.session_state.get("edit_upload_caption", st.session_state._studio_caption)
                                final_tags = st.session_state.get("edit_upload_hashtags", st.session_state._studio_hashtags)
                                full_cap = _publish_caption(final_cap, final_tags)
                                with st.spinner("发布中..."):
                                    ok = post_photo(st.session_state._studio_image, full_cap)
                                if ok:
                                    add_to_history(st.session_state._studio_image, full_cap,
                                                   st.session_state._studio_product)
                                    analytics_increment("posts")
                                    did = draft_save(st.session_state._studio_image, final_cap, final_tags,
                                                     st.session_state._studio_product, category="upload",
                                                     topic=upload_topic if upload_topic != "无" else "")
                                    draft_mark_posted(did)
                                    log_event("post_success", product=st.session_state._studio_product,
                                              message="从图片上传发布")
                                    st.success("✅ 发布成功！")
                                else:
                                    _post_failed(st.session_state._studio_product)
                            else:
                                st.warning("⚠️ 请先在侧边栏登录 Instagram。")
            else:
                st.info("👈 上传一张图片开始")

    # ── Tab 3: Hashtag Tool ──
    with tab3:
        st.markdown("#### 🏷️ AI 标签生成器")
        tag_product = st.text_input("产品/主题", "cutting board", key="tag_product")
        tag_niche = st.text_input("领域", "kitchen gadgets", key="tag_niche")
        tag_strategy = st.selectbox("标签策略", ["mixed", "popular", "niche"], key="tag_strat")

        if st.button("✨ 生成标签", key="gen_tags_btn"):
            with st.spinner("生成中..."):
                tags = generate_hashtags(tag_product, niche=tag_niche, category=tag_strategy)
                st.session_state._studio_hashtags = tags
                st.session_state["tag_output"] = tags
            st.success("标签已生成")

        st.text_area("生成的标签", st.session_state.get("_studio_hashtags", ""), height=100, key="tag_output")
        st.caption(f"共 {len(st.session_state.get('_studio_hashtags', '').split())} 个标签")

    # ── Tab 4: Batch Generate ──
    with tab4:
        st.markdown("#### 📦 批量生成")
        batch_count = st.slider("数量", 1, 10, 3, key="batch_n")
        batch_cat = st.selectbox("品类", list(DEFAULT_CATEGORIES.keys()), key="batch_cat")

        if st.button("⚡ 批量生成", key="batch_btn", type="primary"):
            results = []
            progress = st.progress(0)
            s = get_settings()
            for i in range(batch_count):
                product = random.choice(DEFAULT_CATEGORIES[batch_cat])
                prompt, prod = generate_prompt(product=product, niche=s.get("audience", ""))
                img = generate_image(prompt, provider=s.get("image_model") or "pollinations")
                cap = generate_caption(prod, style=s.get("style", "casual"),
                                       niche=s.get("audience", ""),
                                       model=s.get("llm_model", "qwen/qwen-2.5-7b-instruct"))
                tags = generate_hashtags(prod, niche=s.get("audience", ""))

                if img:
                    asset_add(img, product=prod, category=batch_cat, prompt=prompt)
                    draft_save(img, cap, tags, prod, batch_cat)
                    analytics_increment("generated")
                    results.append((img, prod, cap, tags))
                    log_event("batch_generated", product=prod)
                progress.progress((i + 1) / batch_count)

            st.success(f"✅ 批量生成完成！{len(results)}/{batch_count} 条内容已保存到草稿箱和素材库。")
            for img, prod, cap, tags in results:
                with st.expander(f"{prod}", expanded=False):
                    _show_image(img, prod, width=200)
                    st.caption(cap[:120])


# ═══════════════════════════════════════════════════════════════
#  PAGE: DRAFTS (草稿箱)
# ═══════════════════════════════════════════════════════════════

elif st.session_state._page == "drafts":
    st.markdown('<p class="section-title">📋 草稿箱</p>', unsafe_allow_html=True)

    drafts = draft_get_all()
    draft_num = len(drafts)

    col_info, col_act = st.columns([3, 1])
    with col_info:
        st.caption(f"共 {draft_num} 条草稿")
    with col_act:
        if st.button("🔄 刷新", key="refresh_drafts"):
            st.rerun()

    if not drafts:
        st.info("草稿箱为空。去「内容工作室」生成内容吧！")
    else:
        for i, d in enumerate(drafts):
            with st.expander(f"{i+1}. {d['product']} — {_fmt_ts(d['created_at'])} | {_badge(d['status'])}",
                             expanded=(i == 0)):
                col_img, col_info = st.columns([1, 2])
                with col_img:
                    _show_image(d["image_path"], d["product"])
                with col_info:
                    edit_cap = st.text_area("文案", d["caption"], height=80, key=f"dcap_{d['id']}")
                    edit_tags = st.text_input("标签", d.get("hashtags", ""), key=f"dtag_{d['id']}")

                    col_a, col_b, col_c, col_d, col_e = st.columns(5)
                    with col_a:
                        if st.button("💾 保存", key=f"save_{d['id']}"):
                            draft_update(d["id"], caption=edit_cap, hashtags=edit_tags)
                            st.success("已保存")
                            st.rerun()
                    with col_b:
                        if d["status"] != "review":
                            if st.button("🔍 审核", key=f"review_{d['id']}",
                                        help="提交到审核中心"):
                                draft_update(d["id"], caption=edit_cap, hashtags=edit_tags)
                                draft_submit_review(d["id"])
                                log_event("review_submitted", product=d.get("product", ""),
                                          message="从草稿箱提交审核")
                                st.success("已提交审核")
                                st.rerun()
                    with col_c:
                        if st.button("🗑️ 删除", key=f"del_{d['id']}"):
                            draft_delete(d["id"])
                            st.rerun()
                    with col_d:
                        if st.button("📋 复制", key=f"copy_{d['id']}"):
                            st.code(edit_cap, language=None)
                    with col_e:
                        if d["status"] != "posted":
                            if st.button("🚀 发布", key=f"post_{d['id']}", type="primary"):
                                if _ensure_login():
                                    full_cap = _publish_caption(edit_cap, edit_tags)
                                    with st.spinner("发布中..."):
                                        ok = post_photo(d["image_path"], full_cap)
                                    if ok:
                                        draft_update(d["id"], caption=edit_cap, hashtags=edit_tags)
                                        draft_mark_posted(d["id"])
                                        add_to_history(d["image_path"], full_cap, d["product"])
                                        analytics_increment("posts")
                                        log_event("post_success", product=d["product"], message="从草稿箱发布")
                                        st.success("✅ 发布成功！")
                                        st.rerun()
                                    else:
                                        _post_failed(d["product"])
                                else:
                                    st.warning("⚠️ 请先在侧边栏登录 Instagram。")


# ═══════════════════════════════════════════════════════════════
#  PAGE: ASSETS (素材库)
# ═══════════════════════════════════════════════════════════════

elif st.session_state._page == "assets":
    st.markdown('<p class="section-title">📁 素材库</p>', unsafe_allow_html=True)

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        asset_search = st.text_input("🔍 搜索", key="asset_search", placeholder="产品名/标签...")
    with col_f2:
        cat_stats = asset_get_by_category()
        cat_options = ["全部"] + [c["category"] for c in cat_stats]
        asset_cat = st.selectbox("品类", cat_options, key="asset_cat")
    with col_f3:
        asset_fav = st.checkbox("⭐ 仅收藏", key="asset_fav")

    assets = asset_get_all(
        category="" if asset_cat == "全部" else asset_cat,
        favorite_only=asset_fav,
        search=asset_search,
        limit=100,
    )
    st.caption(f"共 {len(assets)} 张素材 · 总计 {asset_count()} 张")

    if not assets:
        st.info("素材库为空。去「内容工作室」生成图片！")
    else:
        # Grid display
        cols = st.columns(4)
        for i, a in enumerate(assets):
            with cols[i % 4]:
                if Path(a["image_path"]).exists():
                    st.image(str(a["image_path"]), use_container_width=True)
                else:
                    st.image("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><rect fill='%23161b22' width='200' height='200'/><text fill='%238b949e' x='50%25' y='50%25' text-anchor='middle'>No Image</text></svg>")

                st.caption(f"**{a['product']}** · {_fmt_ts(a['created_at'])}")

                col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)
                with col_btn1:
                    fav_label = "⭐" if a["is_favorite"] else "☆"
                    if st.button(fav_label, key=f"fav_{a['id']}", help="切换收藏"):
                        asset_toggle_favorite(a["image_path"])
                        st.rerun()
                with col_btn2:
                    if st.button("✏️", key=f"use_{a['id']}", help="在工作室打开"):
                        st.session_state._studio_image = a["image_path"]
                        st.session_state._studio_product = a["product"]
                        st.session_state._studio_prompt = a.get("prompt", "")
                        st.session_state._page = "studio"
                        st.rerun()
                with col_btn3:
                    pub_key = f"pub_{a['id']}"
                    if st.button("🚀", key=f"pubbtn_{a['id']}", help="快速发布"):
                        st.session_state[pub_key] = not st.session_state.get(pub_key, False)
                with col_btn4:
                    if st.button("🗑️", key=f"adel_{a['id']}", help="删除"):
                        asset_delete(a["image_path"])
                        st.rerun()

                # Quick-publish expander (shown when 🚀 is toggled)
                pub_key = f"pub_{a['id']}"
                if st.session_state.get(pub_key, False):
                    with st.expander("🚀 快速发布", expanded=True):
                        col_cap1, col_cap2 = st.columns([3, 1])
                        with col_cap1:
                            qp_cap = st.text_area(
                                "文案", key=f"qp_cap_{a['id']}",
                                placeholder="写一段吸引人的文案...", height=80,
                            )
                        with col_cap2:
                            st.caption("AI 助手")
                            if st.button("📝 生成文案", key=f"qp_gencap_{a['id']}", use_container_width=True):
                                cap = generate_caption(
                                    a.get("product", "product"),
                                    style=get_settings().get("style", "casual"),
                                    niche=get_settings().get("audience", ""),
                                    model=get_settings().get("llm_model", "qwen/qwen-2.5-7b-instruct"),
                                )
                                st.session_state[f"qp_cap_{a['id']}"] = cap
                                st.rerun()
                            if st.button("🏷️ 生成标签", key=f"qp_ai_{a['id']}", use_container_width=True):
                                tags = generate_hashtags(
                                    a.get("product", ""),
                                    niche=get_settings().get("audience", ""),
                                )
                                st.session_state[f"qp_tag_{a['id']}"] = tags
                                st.rerun()
                        qp_tags = st.text_input(
                            "标签", key=f"qp_tag_{a['id']}",
                            placeholder="#tag1 #tag2",
                        )

                        col_pub1, col_pub2 = st.columns(2)
                        with col_pub1:
                            if st.button("💾 保存草稿", key=f"qp_save_{a['id']}", use_container_width=True):
                                draft_save(
                                    image_path=a["image_path"],
                                    caption=qp_cap,
                                    hashtags=qp_tags,
                                    product=a.get("product", ""),
                                )
                                st.success("已保存到草稿箱")
                        with col_pub2:
                            if st.button("🚀 立即发布", key=f"qp_go_{a['id']}",
                                        use_container_width=True, type="primary"):
                                if _ensure_login():
                                    full_cap = _publish_caption(qp_cap, qp_tags)
                                    with st.spinner("发布中..."):
                                        ok = post_photo(a["image_path"], full_cap)
                                    if ok:
                                        add_to_history(a["image_path"], full_cap, a.get("product", ""))
                                        analytics_increment("posts")
                                        did = draft_save(a["image_path"], qp_cap, qp_tags,
                                                         a.get("product", ""), topic="")
                                        draft_mark_posted(did)
                                        log_event("post_success", product=a.get("product", ""),
                                                  message="从素材库直接发布")
                                        st.session_state[pub_key] = False
                                        st.success("✅ 发布成功！")
                                        st.rerun()
                                    else:
                                        _post_failed(a.get("product", ""))
                                else:
                                    st.warning("⚠️ 请先在侧边栏登录 Instagram。")


# ═══════════════════════════════════════════════════════════════
#  PAGE: CONTENT (内容管理)
# ═══════════════════════════════════════════════════════════════

elif st.session_state._page == "content":
    st.markdown('<p class="section-title">📂 内容管理</p>', unsafe_allow_html=True)

    tab_lib, tab_hist = st.tabs(["📋 内容库", "📝 发布历史"])

    # ── Tab 1: Content Library ──
    with tab_lib:
        # Filter bar
        col_q, col_t, col_g, col_s = st.columns([2, 1.5, 1.5, 1])
        with col_q:
            search_query = st.text_input("🔍 搜索", key="cm_search",
                                         placeholder="关键词匹配文案/产品/标签...")
        with col_t:
            topic_filter = st.selectbox("📂 主题", ["全部"] + TOPIC_KEYS, key="cm_topic")
        with col_g:
            tag_filter = st.text_input("🏷️ 标签筛选", key="cm_tag",
                                       placeholder="输入标签关键词...")
        with col_s:
            status_filter = st.selectbox("📋 状态", ["全部", "draft", "review", "posted"],
                                         key="cm_status",
                                         format_func=lambda x: {"全部": "全部", "draft": "草稿",
                                                               "review": "审核中", "posted": "已发布"}.get(x, x))

        # Execute search
        results = draft_search(
            query=search_query,
            topic="" if topic_filter == "全部" else topic_filter,
            tag=tag_filter.lstrip("#"),
            status="" if status_filter == "全部" else status_filter,
            limit=200,
        )
        st.caption(f"共 {len(results)} 条结果")

        if not results:
            st.info("没有匹配的内容。去「内容工作室」创建内容吧！")
        else:
            # Display results in grid
            cols = st.columns(3)
            for i, r in enumerate(results):
                with cols[i % 3]:
                    # Card container
                    with st.container():
                        _show_image(r["image_path"], r.get("product", ""), width=300)
                        # Topic & status badges
                        badge_html = ""
                        if r.get("topic"):
                            badge_html += f'<span class="badge badge-info">{r["topic"]}</span> '
                        status_label = {"draft": "草稿", "review": "审核中", "posted": "已发布"}.get(r["status"], r["status"])
                        badge_cls = {"draft": "badge-warning", "review": "badge-info", "posted": "badge-success"}.get(r["status"], "badge-warning")
                        badge_html += f'<span class="badge {badge_cls}">{status_label}</span>'
                        st.markdown(badge_html, unsafe_allow_html=True)

                        # Caption preview
                        st.caption(r["caption"][:100] + ("..." if len(r["caption"]) > 100 else ""))

                        # Tags
                        if r.get("hashtags"):
                            tags_list = r["hashtags"].split()[:5]
                            st.caption(" ".join(tags_list))

                        # Footer: date + actions
                        st.caption(f"📅 {_fmt_ts(r['created_at'])}")

                        col_a1, col_a2, col_a3 = st.columns(3)
                        with col_a1:
                            if st.button("✏️", key=f"cm_edit_{r['id']}", help="在工作室打开"):
                                st.session_state._studio_image = r["image_path"]
                                st.session_state._studio_product = r.get("product", "")
                                st.session_state._studio_caption = r["caption"]
                                st.session_state._studio_hashtags = r.get("hashtags", "")
                                st.session_state._page = "studio"
                                st.rerun()
                        with col_a2:
                            if r["status"] != "posted":
                                if st.button("🚀", key=f"cm_post_{r['id']}", help="发布到 Instagram"):
                                    if _ensure_login():
                                        cap = _publish_caption(r["caption"], r.get("hashtags", ""))
                                        with st.spinner("发布中..."):
                                            ok = post_photo(r["image_path"], cap)
                                        if ok:
                                            draft_mark_posted(r["id"])
                                            add_to_history(r["image_path"], cap, r.get("product", ""))
                                            analytics_increment("posts")
                                            log_event("post_success", product=r.get("product", ""),
                                                      message="从内容库发布")
                                            st.success("✅ 已发布")
                                            st.rerun()
                                        else:
                                            _post_failed(r.get("product", ""))
                                    else:
                                        st.warning("⚠️ 请先登录 Instagram")
                        with col_a3:
                            if st.button("🗑️", key=f"cm_del_{r['id']}", help="删除"):
                                draft_delete(r["id"])
                                st.rerun()

    # ── Tab 2: Published History ──
    with tab_hist:
        posted = draft_search(status="posted", limit=200)
        st.caption(f"共 {len(posted)} 条已发布")

        if not posted:
            st.info("还没有发布记录。")
        else:
            # Date filter for history
            dates = sorted(set(r["created_at"][:10] for r in posted), reverse=True)
            hist_date = st.selectbox("按日期筛选", ["全部"] + dates, key="cm_hist_date",
                                     format_func=lambda d: d if d == "全部" else d)

            for r in posted:
                if hist_date != "全部" and r["created_at"][:10] != hist_date:
                    continue
                col_i, col_t = st.columns([1, 3])
                with col_i:
                    _show_image(r["image_path"], "", width=150)
                with col_t:
                    st.caption(f"**{r.get('product', '')}** · {_fmt_ts(r['created_at'])}")
                    if r.get("topic"):
                        st.markdown(f'<span class="badge badge-info">{r["topic"]}</span>',
                                   unsafe_allow_html=True)
                    st.caption(r["caption"][:150])
                    if r.get("hashtags"):
                        st.caption(" ".join(r["hashtags"].split()[:8]))


# ═══════════════════════════════════════════════════════════════
#  PAGE: REVIEW (审核中心)
# ═══════════════════════════════════════════════════════════════

elif st.session_state._page == "review":
    st.markdown('<p class="section-title">🔍 审核中心</p>', unsafe_allow_html=True)

    review_items = draft_get_all("review")
    st.caption(f"待审核: {len(review_items)} 条")

    if not review_items:
        st.info("审核队列为空。在「内容工作室」或「草稿箱」中将内容提交审核。")
    else:
        for i, item in enumerate(review_items):
            with st.container():
                st.markdown(f"---")
                col_img, col_content, col_actions = st.columns([1, 2, 1])

                with col_img:
                    _show_image(item["image_path"], item.get("product", ""))
                    st.caption(f"📅 {_fmt_ts(item['created_at'])}")
                    if item.get("category"):
                        st.caption(f"📂 {item['category']}")

                with col_content:
                    st.markdown("#### ✏️ 文案")
                    edited_caption = st.text_area(
                        "Caption", item["caption"], height=100,
                        key=f"rv_cap_{item['id']}",
                        label_visibility="collapsed",
                    )
                    st.markdown("#### 🏷️ 标签")
                    edited_tags = st.text_input(
                        "Hashtags", item.get("hashtags", ""),
                        key=f"rv_tag_{item['id']}",
                        label_visibility="collapsed",
                    )
                    st.caption(f"共 {len(edited_tags.split())} 个标签")

                with col_actions:
                    st.markdown("##### 操作")
                    # Save edits
                    if st.button("💾 保存修改", key=f"rv_save_{item['id']}", use_container_width=True):
                        draft_update(item["id"], caption=edited_caption, hashtags=edited_tags)
                        st.success("已保存")
                        st.rerun()

                    # Regenerate caption
                    if st.button("🔄 重新生成文案", key=f"rv_recap_{item['id']}", use_container_width=True):
                        with st.spinner("生成中..."):
                            s = get_settings()
                            new_cap = generate_caption(
                                item.get("product", ""),
                                style=s.get("style", "casual"),
                                niche=s.get("audience", ""),
                                model=s.get("llm_model", "qwen/qwen-2.5-7b-instruct"),
                            )
                            draft_update(item["id"], caption=new_cap)
                        st.success("文案已重新生成")
                        st.rerun()

                    # Regenerate hashtags
                    if st.button("🔄 重新生成标签", key=f"rv_retag_{item['id']}", use_container_width=True):
                        with st.spinner("生成中..."):
                            s = get_settings()
                            new_tags = generate_hashtags(
                                item.get("product", ""),
                                niche=s.get("audience", ""),
                            )
                            draft_update(item["id"], hashtags=new_tags)
                        st.success("标签已重新生成")
                        st.rerun()

                    st.markdown("---")

                    # Approve → move to draft
                    if st.button("✅ 批准发布", key=f"rv_appr_{item['id']}", use_container_width=True, type="primary"):
                        draft_update(item["id"], caption=edited_caption, hashtags=edited_tags)
                        draft_approve(item["id"])
                        log_event("review_approved", product=item.get("product", ""),
                                  message="审核通过，已移至草稿箱")
                        st.success("已批准！移至草稿箱。")
                        st.rerun()

                    # Reject → delete
                    if st.button("❌ 删除", key=f"rv_rej_{item['id']}", use_container_width=True):
                        draft_reject(item["id"])
                        log_event("review_rejected", product=item.get("product", ""),
                                  message="审核未通过，已删除")
                        st.warning("已删除")
                        st.rerun()

        # Bulk approve all
        if len(review_items) > 1:
            st.markdown("---")
            if st.button("✅ 全部批准", use_container_width=True, type="primary"):
                for it in review_items:
                    draft_update(
                        it["id"],
                        caption=st.session_state.get(f"rv_cap_{it['id']}", it["caption"]),
                        hashtags=st.session_state.get(f"rv_tag_{it['id']}", it.get("hashtags", "")),
                    )
                    draft_approve(it["id"])
                log_event("review_bulk_approved", message=f"批量批准 {len(review_items)} 条")
                st.success(f"已批准 {len(review_items)} 条，全部移至草稿箱。")
                st.rerun()


# ═══════════════════════════════════════════════════════════════
#  PAGE: HISTORY (发布记录)
# ═══════════════════════════════════════════════════════════════

elif st.session_state._page == "history":
    st.markdown('<p class="section-title">📝 发布记录</p>', unsafe_allow_html=True)

    records = get_history()
    st.caption(f"共 {len(records)} 条发布记录")

    if not records:
        st.info("还没有发布记录。")
    else:
        cols = st.columns(3)
        for i, r in enumerate(records):
            with cols[i % 3]:
                _show_image(r["image_path"], r["product"])
                st.caption(f"📅 {_fmt_ts(r['posted_at'])}")
                with st.expander("文案", expanded=False):
                    st.text(r["caption"][:300])

        if st.button("🗑️ 清空记录", key="clear_hist"):
            clear_history()
            st.rerun()


# ═══════════════════════════════════════════════════════════════
#  PAGE: ANALYTICS (数据统计)
# ═══════════════════════════════════════════════════════════════

elif st.session_state._page == "analytics":
    st.markdown('<p class="section-title">📈 数据统计</p>', unsafe_allow_html=True)

    totals = analytics_totals()
    overview = analytics_overview(30)

    # Metric cards
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.markdown(f"""<div class="metric-card">
            <div class="number">{totals.get('generated', 0)}</div>
            <div class="label">🖼️ 总生成</div></div>""", unsafe_allow_html=True)
    with col_m2:
        st.markdown(f"""<div class="metric-card">
            <div class="number">{totals.get('posts', 0)}</div>
            <div class="label">🚀 总发布</div></div>""", unsafe_allow_html=True)
    with col_m3:
        st.markdown(f"""<div class="metric-card">
            <div class="number">{draft_count()}</div>
            <div class="label">📋 草稿数</div></div>""", unsafe_allow_html=True)
    with col_m4:
        st.markdown(f"""<div class="metric-card">
            <div class="number">{asset_count()}</div>
            <div class="label">📁 素材数</div></div>""", unsafe_allow_html=True)

    # Daily chart
    st.markdown("#### 📊 每日趋势 (近30天)")
    if overview:
        chart_data = []
        for r in reversed(overview):
            chart_data.append({
                "日期": r["date"][5:],
                "生成": r["generated"],
                "发布": r["posts"],
            })
        st.bar_chart(chart_data, x="日期", y=["生成", "发布"])

    # Category breakdown
    st.markdown("#### 🏷️ 品类分布")
    cats = asset_get_by_category()
    if cats:
        cat_data = [{"品类": c["category"], "数量": c["cnt"]} for c in cats]
        st.bar_chart(cat_data, x="品类", y="数量", horizontal=True)

    # Recent activity
    st.markdown("#### 🕐 最近活动")
    acts = get_recent_activity(15)
    for a in acts:
        sev = a.get("severity", "info")
        icon = {"info": "ℹ️", "warn": "⚠️", "error": "❌"}.get(sev, "ℹ️")
        st.caption(f"{icon} {_fmt_ts(a['created_at'])} — {a.get('event','')}: {a.get('message','')}")


# ═══════════════════════════════════════════════════════════════
#  PAGE: SETTINGS (设置)
# ═══════════════════════════════════════════════════════════════

elif st.session_state._page == "settings":
    st.markdown('<p class="section-title">⚙️ 设置</p>', unsafe_allow_html=True)

    s = get_settings()

    _or_ok = bool(OPENROUTER_API_KEY) and not OPENROUTER_API_KEY.startswith("your-")
    _gm_ok = bool(GEMINI_API_KEY)
    st.caption(
        ("✅ OpenRouter Key 已配置" if _or_ok else "❌ OpenRouter Key 未配置") + "  ·  " +
        ("✅ Gemini Key 已配置" if _gm_ok else
         "⚠️ Gemini Key 未配置（图片质量更好，免费 500 张/天，去 aistudio.google.com 申请后填入 ins账号自动化/data/.env）")
    )

    tab_s1, tab_s2, tab_s3 = st.tabs(["🎯 品牌 & 内容", "🤖 AI 模型", "🏷️ 默认标签"])

    with tab_s1:
        st.markdown("#### 🎯 品牌信息")
        new_niche = st.text_input("内容定位", s.get("niche", ""),
                                   help="例如: kitchen gadgets & home bar")
        new_audience = st.text_input("目标受众", s.get("audience", ""),
                                      help="例如: home cooks, juice lovers")
        new_style = st.selectbox("默认文案风格", list(CAPTION_STYLES.keys()),
                                  index=list(CAPTION_STYLES.keys()).index(s.get("style", "casual"))
                                  if s.get("style", "casual") in CAPTION_STYLES else 0)
        new_instructions = st.text_area("文案额外指令", s.get("caption_instructions", ""),
                                         help="额外提示词，如 'use emojis', 'keep under 150 chars'")

        if st.button("💾 保存品牌设置", key="save_brand"):
            save_settings(
                niche=new_niche, audience=new_audience, style=new_style,
                caption_instructions=new_instructions,
            )
            st.success("品牌设置已保存")

    with tab_s2:
        st.markdown("#### 🤖 AI 模型配置")
        new_llm = st.text_input("文案模型", s.get("llm_model", "qwen/qwen-2.5-7b-instruct"),
                                 help="OpenRouter 模型 ID")
        _img_opts = ["gemini", "pollinations", "openrouter"]
        _saved_img = s.get("image_model", "gemini")
        new_img = st.selectbox("图片模型", _img_opts,
                                index=_img_opts.index(_saved_img) if _saved_img in _img_opts else 0,
                                help="gemini 需要 GEMINI_API_KEY（免费 500 张/天）；openrouter 需要余额；pollinations 免费但质量一般")

        if st.button("💾 保存模型配置", key="save_models"):
            save_settings(llm_model=new_llm, image_model=new_img)
            st.success("模型配置已保存")

    with tab_s3:
        st.markdown("#### 🏷️ 默认标签")
        new_tags = st.text_area("Hashtags", s.get("hashtags", ""), height=100,
                                 help="发布时自动追加的标签，空格分隔")
        st.caption("💡 在「内容工作室 → 标签工具」中可以为每条内容生成专属标签。")

        if st.button("💾 保存标签", key="save_tags"):
            save_settings(hashtags=new_tags)
            st.success("标签已保存")

    st.markdown("---")
    st.markdown("#### ⚠️ 危险操作")
    if st.button("🔄 重置所有设置", type="secondary"):
        for k in ("niche", "audience", "style", "caption_instructions",
                  "llm_model", "image_model", "hashtags"):
            save_settings(**{k: ""})
        st.warning("设置已重置，刷新后生效。")


# ═══════════════════════════════════════════════════════════════
#  INIT
# ═══════════════════════════════════════════════════════════════

# Auto-restore session on startup
if not st.session_state.authenticated and SESSION_FILE.exists():
    st.session_state.authenticated = True
