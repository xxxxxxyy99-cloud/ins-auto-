"""Scheduled generation core: one piece of content per run.

Used by worker.py (one-shot run in its own process) and by scheduler.py
(the long-running schedule watcher). Posting is manual — this module
only ever produces drafts in the draft box.
"""

import random
from datetime import datetime, time, timedelta

from .content import (
    generate_prompt, generate_image, generate_caption, generate_hashtags,
    DEFAULT_CATEGORIES, DEFAULT_CAPTION_MODEL,
)
from .db import get_settings, draft_save, analytics_increment
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
#  Auto generate pipeline
# ═══════════════════════════════════════════════════════════

def _pick_product(settings: dict) -> tuple[str, str]:
    category = settings.get("schedule_category", "") or ""
    if category not in DEFAULT_CATEGORIES:
        category = random.choice(list(DEFAULT_CATEGORIES.keys()))
    return random.choice(DEFAULT_CATEGORIES[category]), category


def run_auto_generate(dry_run: bool = False) -> dict:
    """Generate one piece of content and save it as a draft.

    Returns {"ok": bool, "stage": str, ...}. Expected failures (image
    engine down) are returned, not raised, and are recorded in the
    activity log and the error counter. Posting is manual: the draft
    box is the hand-off point.
    """
    settings = get_settings()
    product, category = _pick_product(settings)
    niche = settings.get("audience", "")
    style = settings.get("style", "casual")
    model = settings.get("llm_model", DEFAULT_CAPTION_MODEL)
    provider = settings.get("image_model") or "pollinations"
    instructions = settings.get("caption_instructions", "")

    log.info("auto_generate_start", product=product,
             message="自动生成开始" + ("（测试模式）" if dry_run else ""))

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
    try:
        tags = generate_hashtags(product_name, niche=niche, model=model)
    except Exception:
        tags = settings.get("hashtags", "")

    if dry_run:
        log.info("auto_generate_dry_run", product=product_name,
                 message="测试模式：已生成，未存入草稿箱")
        return {"ok": True, "stage": "dry_run", "product": product_name,
                "image": img_path, "caption": caption, "hashtags": tags,
                "draft_id": None}

    # 3) save into the draft box — the hand-off point for manual posting
    did = draft_save(img_path, caption, tags, product_name, category, topic="")
    analytics_increment("generated")
    log.info("auto_generated", product=product_name,
             message="自动生成完成，已存入草稿箱（等你手动发布）")
    return {"ok": True, "stage": "done", "product": product_name,
            "image": img_path, "caption": caption, "hashtags": tags,
            "draft_id": did}
