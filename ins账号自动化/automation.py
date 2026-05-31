"""Automation scheduling and background posting logic."""

import secrets
import time
from datetime import datetime, timedelta

from .config import POST_INTERVAL_DAYS, POST_WINDOW_START, POST_WINDOW_END
from . import db
from .state import StateMachine, State
from .logger import get_logger
from .content import generate_prompt, generate_image, generate_caption, build_caption
from .bot import login, post_photo, SESSION_FILE

log = get_logger("automation")


# ─── Schedule ───────────────────────────────────────────────

def get_scheduled_time() -> datetime | None:
    data = db.schedule_get()
    raw = data.get("next_post")
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except:
            pass
    return None


def generate_scheduled_time(interval_days: int | None = None) -> datetime:
    interval = interval_days or POST_INTERVAL_DAYS
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    data = db.schedule_get()
    last_raw = data.get("last_post")
    if last_raw:
        try:
            last_post = datetime.fromisoformat(last_raw)
            target_day = last_post + timedelta(days=interval)
        except Exception:
            target_day = today
    else:
        target_day = today

    hour = secrets.randbelow(POST_WINDOW_END - POST_WINDOW_START + 1) + POST_WINDOW_START
    minute = secrets.randbelow(60)
    target = target_day.replace(hour=hour, minute=minute)

    if target <= datetime.now():
        target_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        hour = secrets.randbelow(POST_WINDOW_END - POST_WINDOW_START + 1) + POST_WINDOW_START
        minute = secrets.randbelow(60)
        target = target_day.replace(hour=hour, minute=minute)

    db.schedule_save({"next_post": target.isoformat(), "next_interval": interval})
    log.info("schedule_updated", message=f"下次发布: {target.strftime('%m-%d %H:%M')} (间隔{interval}d)")
    return target


def next_post_delay(interval_days: int | None = None) -> float:
    interval = interval_days or POST_INTERVAL_DAYS
    data = db.schedule_get()
    stored_interval = data.get("next_interval")
    sched = get_scheduled_time()

    if sched is None or sched <= datetime.now() or stored_interval != interval:
        # Schedule is overdue or missing — check if we should post now
        last_raw = data.get("last_post")
        in_window = _in_posting_window()
        if in_window:
            # We're in the posting window → post now, don't wait
            log.info("immediate_post", message="发布窗口内且已逾期，立即发布")
            sched = datetime.now()  # triggers delay=0
        elif last_raw:
            # Outside window but have posted before → schedule next window
            sched = generate_scheduled_time(interval_days)
        else:
            # First run, not in window → schedule next window
            sched = generate_scheduled_time(interval_days)

    delta = (sched - datetime.now()).total_seconds()
    log.debug("delay_check", message=f"距下次发布: {delta/3600:.1f}h")
    return max(delta, 0)


def _in_posting_window() -> bool:
    """Check if current hour is within the allowed posting window."""
    now = datetime.now()
    return POST_WINDOW_START <= now.hour < POST_WINDOW_END


def save_last_post():
    settings = db.settings_get()
    interval = int(settings.get("interval_days", POST_INTERVAL_DAYS))
    db.schedule_save({"last_post": datetime.now().isoformat()})
    generate_scheduled_time(interval)
    log.info("post_completed", message="发布完成，已生成下次排期")


# ─── Background worker ──────────────────────────────────────

MAX_CONSECUTIVE_ERRORS = 5
# Fatal errors that should stop automation immediately
FATAL_KEYWORDS = [
    "checkpoint_required", "challenge_required", "account disabled",
    "password", "invalid credentials", "banned", "suspended",
    "feedback_required",
]


def _is_fatal(error_msg: str) -> bool:
    """Check if error is fatal (account-level) vs transient (network/etc)."""
    lower = error_msg.lower()
    return any(kw in lower for kw in FATAL_KEYWORDS)


def automation_worker(username: str, sessionid: str = "", stop_check=None):
    sm = StateMachine()
    consecutive_errors = 0
    total_cycles = 0

    while not stop_check():
        try:
            total_cycles += 1
            sm.set_running(True)
            settings = db.settings_get()
            interval = int(settings.get("interval_days", 2))
            niche = settings.get("niche", "")
            audience = settings.get("audience", "")
            style = settings.get("style", "casual")
            llm_model = settings.get("llm_model", "qwen/qwen-2.5-7b-instruct")
            image_model = settings.get("image_model", "")
            caption_instructions = settings.get("caption_instructions", "")
            hashtags_raw = settings.get("hashtags", "")

            # ── Wait for scheduled time ──
            delay = next_post_delay(interval)
            log.info("waiting", message=f"等待 {delay/3600:.1f}h 到下次发布 (第{total_cycles}轮)")
            deadline = datetime.now().timestamp() + delay
            while True:
                if stop_check():
                    sm.set_running(False)
                    return
                remaining = deadline - datetime.now().timestamp()
                if remaining <= 0:
                    break  # time to post!
                # Sleep in chunks, but re-check real time each iteration
                # so system sleep/hibernate doesn't make us miss the window
                chunk = min(60, remaining)
                time.sleep(chunk)

            if stop_check():
                sm.set_running(False)
                return

            # ── Step 1: Generate content ──
            sm.transition(State.GENERATING)
            log.info("generating", message="正在生成内容...")

            prompt, product = generate_prompt(niche=niche)
            image_path = None
            for gen_retry in range(5):
                image_path = generate_image(prompt, model=image_model or None)
                if image_path:
                    break
                log.warn("generate_retry", product=product,
                         message=f"图片生成重试 {gen_retry+1}/5")
                time.sleep(10 * (gen_retry + 1))

            if not image_path:
                log.warn("generate_failed", product=product, message="图片生成失败5次，跳过本轮")
                time.sleep(30)
                continue  # don't count as error, just skip cycle

            caption = generate_caption(product, style=style, niche=audience or niche,
                                       model=llm_model, instructions=caption_instructions)
            if hashtags_raw.strip():
                caption = build_caption(caption, product, hashtags_raw.split())
            log.info("content_generated", product=product, message="内容生成成功")

            # ── Step 2: Queue ──
            sm.transition(State.QUEUED)
            db.queue_push(image_path, caption, product)
            db.analytics_increment("generated")
            db.analytics_increment("queue_added")
            log.info("content_queued", product=product, message="已加入发布队列")

            # ── Step 3: Post ──
            sm.transition(State.POSTING)
            log.info("posting", product=product, message="正在发布到 Instagram...")

            cl = login(username, sessionid=sessionid)
            post = db.queue_pop()
            if post:
                success = post_photo(post["image_path"], post["caption"])
                if success:
                    db.queue_mark_posted(post["id"])
                    db.history_add(post["image_path"], post["caption"], post["product"])
                    db.analytics_increment("posts")
                    save_last_post()
                    sm.transition(State.POSTED)
                    db.log_event("post_success", product=product, message="发布成功")
                    consecutive_errors = 0  # reset on success
                    log.info("cycle_done", message=f"第{total_cycles}轮完成")
                else:
                    db.queue_mark_pending(post["id"])
                    raise Exception("发布失败 (instagrapi)")
            else:
                log.warn("queue_empty", message="队列为空，跳过发布")
                consecutive_errors = 0  # empty queue is not an error

            sm.transition(State.IDLE)

        except Exception as e:
            err_msg = str(e)[:300]
            consecutive_errors += 1
            sm.record_error(err_msg)
            db.analytics_increment("errors")

            if _is_fatal(err_msg):
                log.error("fatal_error", message=f"致命错误，停止自动化: {err_msg}")
                sm.set_running(False)
                return

            # Transient error: log and continue with backoff
            backoff = min(60 * (2 ** (consecutive_errors - 1)), 3600)  # 1m → 2m → 4m → 8m → ... max 1h
            log.error("cycle_failed",
                      message=f"第{total_cycles}轮失败 ({consecutive_errors}连错, {backoff}s后重试): {err_msg}")
            time.sleep(backoff)
