"""Scheduled auto-posting core: content generation + publishing pipeline.

Used by worker.py (one-shot run in its own process, so Playwright never
shares a thread or event loop with Streamlit or Tkinter) and by
scheduler.py (the long-running schedule watcher).
"""

import random
from datetime import datetime, time, timedelta

from .content import (
    generate_prompt, generate_image, generate_caption, generate_hashtags,
    build_caption, DEFAULT_CATEGORIES, DEFAULT_CAPTION_MODEL,
)
from .db import (
    get_settings, draft_save, draft_mark_posted, add_to_history,
    analytics_increment,
)
from .bot import post_photo, SESSION_FILE
from .logger import get_logger

log = get_logger("automation")


# ═══════════════════════════════════════════════════════════
#  Schedule computation
# ═══════════════════════════════════════════════════════════

def _parse_hhmm(value: str, fallback: time = time(10, 0)) -> time:
    try:
        hh, mm = str(value).split(":")[:2]
        return time(int(hh), int(mm))
    except Exception:
        return fallback


def compute_next_run(settings: dict, now: datetime | None = None) -> datetime | None:
    """Next scheduled run time, or None when scheduling is disabled.

    daily mode: every day at scheduled_time.
    interval mode: every `interval_days` days at scheduled_time, anchored
    on the last run. When a target is already in the past the scheduler
    fires immediately (catch-up), so a closed laptop just runs late.
    """
    if str(settings.get("schedule_enabled", "0")) != "1":
        return None

    now = now or datetime.now()
    at = _parse_hhmm(settings.get("scheduled_time", "10:00"))
    mode = settings.get("schedule_mode", "interval")
    try:
        interval = max(1, int(settings.get("interval_days", "2") or 2))
    except (TypeError, ValueError):
        interval = 2
    step_days = 1 if mode == "daily" else interval

    try:
        last_dt = datetime.fromisoformat(settings.get("schedule_last_run", ""))
    except Exception:
        last_dt = None

    if last_dt is None:
        candidate = datetime.combine(now.date(), at)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    return datetime.combine(last_dt.date(), at) + timedelta(days=step_days)


# ═══════════════════════════════════════════════════════════
#  Auto post pipeline
# ═══════════════════════════════════════════════════════════

def _pick_product(settings: dict) -> tuple[str, str]:
    category = settings.get("schedule_category", "") or ""
    if category not in DEFAULT_CATEGORIES:
        category = random.choice(list(DEFAULT_CATEGORIES.keys()))
    return random.choice(DEFAULT_CATEGORIES[category]), category


def run_auto_post(dry_run: bool = False) -> dict:
    """Generate one piece of content and publish it to Instagram.

    Returns {"ok": bool, "stage": str, ...}. Expected failures (image
    engine down, not logged in, unclear share result) are returned, not
    raised, and are recorded in the activity log and error counter.
    """
    settings = get_settings()
    product, category = _pick_product(settings)
    niche = settings.get("audience", "")
    style = settings.get("style", "casual")
    model = settings.get("llm_model", DEFAULT_CAPTION_MODEL)
    provider = settings.get("image_model") or "pollinations"
    instructions = settings.get("caption_instructions", "")

    log.info("auto_start", product=product,
             message=f"定时发布开始（{'演示模式' if dry_run else '正式发布'}）")

    # 1) image
    prompt, product_name = generate_prompt(product=product, niche=niche, category=category)
    img_path = generate_image(prompt, provider=provider)
    if not img_path:
        log.error("auto_image_failed", product=product_name, message="所有图片引擎都失败")
        analytics_increment("errors")
        return {"ok": False, "stage": "image", "message": "图片生成失败"}

    # 2) caption + hashtags
    caption = generate_caption(product_name, style=style, niche=niche,
                               model=model, instructions=instructions)
    tags = generate_hashtags(product_name, niche=niche, model=model)

    try:
        limit = int(settings.get("publish_hashtag_limit", "15") or 15)
    except (TypeError, ValueError):
        limit = 15
    full_caption = build_caption(caption, tags.split() if tags else None, limit=limit)

    analytics_increment("generated")

    # 3) record as draft, then publish
    did = draft_save(img_path, caption, tags, product_name, category, topic="")

    if dry_run:
        log.info("auto_dry_run", product=product_name, message="演示模式：已生成草稿，未发布")
        return {"ok": True, "stage": "dry_run", "product": product_name,
                "image": img_path, "caption": caption, "hashtags": tags, "draft_id": did}

    if not SESSION_FILE.exists():
        log.error("auto_not_logged_in", product=product_name,
                  message="未登录 Instagram，跳过本次自动发布")
        analytics_increment("errors")
        return {"ok": False, "stage": "login",
                "message": "未登录 Instagram，请先在网页面板登录一次"}

    headless = str(settings.get("scheduler_headless", "0")) == "1"
    ok = post_photo(img_path, full_caption, headless=headless)
    if ok:
        draft_mark_posted(did)
        add_to_history(img_path, full_caption, product_name)
        analytics_increment("posts")
        log.info("auto_posted", product=product_name, message="自动发布成功")
        return {"ok": True, "stage": "posted", "product": product_name, "draft_id": did}

    log.error("auto_post_failed", product=product_name,
              message="自动发布失败（Instagram 未确认发布成功）")
    analytics_increment("errors")
    return {"ok": False, "stage": "post",
            "message": "发布未确认成功，检查 data/post_unconfirmed.png"}
