"""Standalone scheduler — runs independently of Streamlit.

Start with: python scheduler.py
Stop with:  Ctrl+C

This process handles the full cycle:
1. Wait until scheduled time
2. Generate image + caption
3. Post to Instagram
4. Schedule next post
5. Repeat
"""

import sys
import time
import signal
import random
from datetime import datetime, timedelta
from pathlib import Path

# Add parent to path so we can import the package
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ins账号自动化.config import POST_INTERVAL_DAYS, POST_WINDOW_START, POST_WINDOW_END, IG_USERNAME
from ins账号自动化.db import (
    init_db, settings_get, schedule_get, schedule_save,
    queue_push, queue_pop, queue_mark_posted, queue_mark_pending,
    history_add, analytics_increment, log_event,
    state_set, state_get,
)
from ins账号自动化.content import generate_prompt, generate_image, generate_caption, build_caption
from ins账号自动化.bot import login, post_photo

init_db()

RUNNING = True


def _in_posting_window() -> bool:
    h = datetime.now().hour
    return POST_WINDOW_START <= h < POST_WINDOW_END


def get_schedule() -> datetime | None:
    data = schedule_get()
    raw = data.get("next_post")
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            pass
    return None


def make_schedule(interval_days: int):
    """Create next scheduled time within the posting window."""
    last_raw = schedule_get().get("last_post")
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if last_raw:
        try:
            last = datetime.fromisoformat(last_raw)
            target_day = last + timedelta(days=interval_days)
        except Exception:
            target_day = today
    else:
        target_day = today
    hour = random.randint(POST_WINDOW_START, POST_WINDOW_END - 1)
    minute = random.randint(0, 59)
    target = target_day.replace(hour=hour, minute=minute)
    if target <= datetime.now():
        target = today + timedelta(days=1)
        target = target.replace(hour=hour, minute=minute)
    schedule_save({"next_post": target.isoformat(), "next_interval": interval_days})
    print(f"[scheduler] 下次发布: {target.strftime('%Y-%m-%d %H:%M')}")
    return target


def wait_until(target: datetime):
    """Sleep until target time, checking every 60s."""
    while RUNNING:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            return  # time to go!
        hrs = remaining / 3600
        print(f"[scheduler] {target.strftime('%H:%M')} 发布, 等待 {hrs:.1f}h ...", flush=True)
        sleep_for = min(300, remaining)  # sleep up to 5 min at a time
        time.sleep(sleep_for)


def do_post(settings: dict):
    """Execute one post cycle: generate → post → schedule next."""
    niche = settings.get("niche", "")
    audience = settings.get("audience", "")
    style = settings.get("style", "casual")
    llm_model = settings.get("llm_model", "qwen/qwen-2.5-7b-instruct")
    image_model = settings.get("image_model", "")
    caption_instructions = settings.get("caption_instructions", "")
    hashtags_raw = settings.get("hashtags", "")
    interval = int(settings.get("interval_days", 2))

    # ── Generate content ──
    print("[scheduler] 正在生成内容...")
    state_set(state="generating", running=True)
    prompt, product = generate_prompt(niche=niche)

    # Try to generate image with retries
    image_path = None
    for retry in range(5):
        image_path = generate_image(prompt, model=image_model or None)
        if image_path:
            break
        print(f"  Image gen retry {retry+1}/5...")
        time.sleep(15 * (retry + 1))

    if not image_path:
        print("[scheduler] 图片生成失败，跳过本轮")
        log_event("gen_failed", product=product, severity="warn", message="图片生成5次均失败")
        return False

    caption = generate_caption(product, style=style, niche=audience or niche,
                               model=llm_model, instructions=caption_instructions)
    if hashtags_raw.strip():
        caption = build_caption(caption, hashtags_raw.split())

    print(f"[scheduler] 产品: {product}")
    print(f"[scheduler] 图片: {image_path}")
    print(f"[scheduler] 文案: {caption[:80]}...")

    # ── Queue and post ──
    queue_push(image_path, caption, product)
    analytics_increment("generated")
    analytics_increment("queue_added")

    state_set(state="posting", running=True)
    print("[scheduler] 登录 Instagram...")

    # Get sessionid from DB settings
    ig_sessionid = settings.get("ig_sessionid", "")
    try:
        cl = login(IG_USERNAME, sessionid=ig_sessionid)
        post = queue_pop()
        if not post:
            print("[scheduler] 队列为空")
            return False

        success = post_photo(post["image_path"], post["caption"])
        if success:
            queue_mark_posted(post["id"])
            history_add(post["image_path"], post["caption"], post["product"])
            analytics_increment("posts")
            schedule_save({"last_post": datetime.now().isoformat()})
            make_schedule(interval)
            state_set(state="idle", running=True)
            log_event("post_success", product=product, message="发布成功")
            print(f"[scheduler] ✅ 发布成功: {product}")
            return True
        else:
            queue_mark_pending(post["id"])
            print("[scheduler] ❌ 发布失败")
            log_event("post_failed", product=product, severity="error", message="post_photo 返回 False")
            return False
    except Exception as e:
        err = str(e)[:200]
        print(f"[scheduler] ❌ 发布异常: {err}")
        log_event("post_exception", product=product, severity="error", message=err)
        return False


def run():
    global RUNNING
    print("=" * 50)
    print("  InsAuto Scheduler — 独立调度器")
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    settings = settings_get()
    interval = int(settings.get("interval_days", 2))
    sched = get_schedule()

    # Decide what to do now
    if sched and sched <= datetime.now():
        # Overdue — post now if in window
        if _in_posting_window():
            print("[scheduler] 发布逾期且在窗口内，立即发布...")
            state_set(state="idle", running=True)
            do_post(settings)
        else:
            # Outside window, schedule next
            print("[scheduler] 发布逾期但不在窗口内，排下一个时间")
            make_schedule(interval)
    elif sched is None:
        # No schedule yet — create one, or post now
        if _in_posting_window():
            print("[scheduler] 首次运行，立即发布...")
            state_set(state="idle", running=True)
            do_post(settings)
        else:
            make_schedule(interval)
    else:
        print(f"[scheduler] 已有排期: {sched.strftime('%Y-%m-%d %H:%M')}")
        state_set(state="idle", running=True)

    # ── Main loop ──
    consecutive_fails = 0
    while RUNNING:
        sched = get_schedule()
        if sched is None:
            make_schedule(interval)
            sched = get_schedule()
        if sched is None:
            time.sleep(60)
            continue

        if sched <= datetime.now():
            if _in_posting_window():
                ok = do_post(settings)
                if ok:
                    consecutive_fails = 0
                else:
                    consecutive_fails += 1
                    backoff = min(300 * (2 ** consecutive_fails), 7200)  # 5m→10m→...max 2h
                    print(f"[scheduler] 失败 {consecutive_fails} 次，{backoff}s 后重试")
                    schedule_save({"next_post": (datetime.now() + timedelta(seconds=backoff)).isoformat()})
            else:
                # Missed window, push to next
                make_schedule(interval)
        else:
            consecutive_fails = 0  # reset on clean wait
            wait_until(sched)


def main():
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    try:
        run()
    except KeyboardInterrupt:
        print("\n[scheduler] 已停止")
    except Exception as e:
        print(f"[scheduler] 致命错误: {e}")
        log_event("scheduler_crash", severity="error", message=str(e)[:300])
        state_set(state="error", running=False, last_error=str(e)[:300])


if __name__ == "__main__":
    main()
