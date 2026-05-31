"""CLI interface — gen/post/go/schedule commands."""

import sys
import time
from datetime import datetime

from .config import IG_USERNAME, IG_PASSWORD
from . import db
from .content import generate_prompt, generate_image, generate_caption, build_caption
from .bot import login, post_photo
from .automation import next_post_delay, save_last_post, generate_scheduled_time
from .logger import get_logger

log = get_logger("cli")


def generate_and_queue(count: int = 1):
    settings = db.settings_get()
    niche = settings.get("niche", "")
    style = settings.get("style", "casual")
    audience = settings.get("audience", "")
    llm_model = settings.get("llm_model", "qwen/qwen-2.5-7b-instruct")
    image_model = settings.get("image_model", "")
    caption_instructions = settings.get("caption_instructions", "")
    hashtags_raw = settings.get("hashtags", "")

    for i in range(count):
        print(f"[{i+1}/{count}] Generating...")
        try:
            prompt, product = generate_prompt(niche=niche)
            image_path = generate_image(prompt, model=image_model or None)
            if not image_path:
                print(f"  [{i+1}/{count}] Image generation failed, skipping")
                continue
            caption = generate_caption(product, style=style, niche=audience or niche,
                                       model=llm_model, instructions=caption_instructions)
            if hashtags_raw.strip():
                caption = build_caption(caption, product, hashtags_raw.split())
            db.queue_push(image_path, caption, product)
            db.analytics_increment("generated")
            print(f"  [{i+1}/{count}] Queued: {product}")
        except Exception as e:
            print(f"  [{i+1}/{count}] Error: {e}")
    print(f"Done. Queue has {db.queue_count()} items.")


def post_from_queue(count: int = 1):
    cl = login(IG_USERNAME, IG_PASSWORD)
    for i in range(count):
        post = db.queue_pop()
        if not post:
            print(f"[{i+1}/{count}] Queue is empty")
            break
        try:
            success = post_photo(post["image_path"], post["caption"])
            if success:
                db.queue_mark_posted(post["id"])
                db.history_add(post["image_path"], post["caption"], post["product"])
                db.analytics_increment("posts")
                save_last_post()
                print(f"  [{i+1}/{count}] Posted: {post['product']}")
            else:
                db.queue_mark_pending(post["id"])
                print(f"  [{i+1}/{count}] Post failed, re-queued")
        except Exception as e:
            db.queue_mark_pending(post["id"])
            print(f"  [{i+1}/{count}] Error: {e}")


def generate_and_post(count: int = 1):
    cl = login(IG_USERNAME, IG_PASSWORD)
    settings = db.settings_get()
    niche = settings.get("niche", "")
    style = settings.get("style", "casual")
    audience = settings.get("audience", "")
    llm_model = settings.get("llm_model", "qwen/qwen-2.5-7b-instruct")
    image_model = settings.get("image_model", "")
    caption_instructions = settings.get("caption_instructions", "")
    hashtags_raw = settings.get("hashtags", "")

    for i in range(count):
        print(f"[{i+1}/{count}] Generating & posting...")
        try:
            prompt, product = generate_prompt(niche=niche)
            image_path = generate_image(prompt, model=image_model or None)
            if not image_path:
                print(f"  [{i+1}/{count}] Image generation failed")
                continue
            caption = generate_caption(product, style=style, niche=audience or niche,
                                       model=llm_model, instructions=caption_instructions)
            if hashtags_raw.strip():
                caption = build_caption(caption, product, hashtags_raw.split())
            success = post_photo(image_path, caption)
            if success:
                db.history_add(image_path, caption, product)
                db.analytics_increment("generated")
                db.analytics_increment("posts")
                save_last_post()
                print(f"  [{i+1}/{count}] Posted: {product}")
            else:
                db.queue_push(image_path, caption, product)
                print(f"  [{i+1}/{count}] Post failed, queued instead")
        except Exception as e:
            print(f"  [{i+1}/{count}] Error: {e}")
    print("Done.")


def run_scheduler():
    print("Scheduler started. Press Ctrl+C to stop.")
    cl = login(IG_USERNAME, IG_PASSWORD)
    while True:
        try:
            settings = db.settings_get()
            interval = int(settings.get("interval_days", 2))
            niche = settings.get("niche", "")
            audience = settings.get("audience", "")
            style = settings.get("style", "casual")
            llm_model = settings.get("llm_model", "openai/gpt-4o-mini")
            image_model = settings.get("image_model", "")
            caption_instructions = settings.get("caption_instructions", "")
            hashtags_raw = settings.get("hashtags", "")

            delay = next_post_delay(interval)
            print(f"Next post in {delay/3600:.1f}h ({datetime.now().strftime('%H:%M')})")
            time.sleep(delay)

            prompt, product = generate_prompt(niche=niche)
            image_path = generate_image(prompt, model=image_model or None)
            if not image_path:
                print("Image failed, retrying in 60s")
                time.sleep(60)
                continue
            caption = generate_caption(product, style=style, niche=audience or niche,
                                       model=llm_model, instructions=caption_instructions)
            if hashtags_raw.strip():
                caption = build_caption(caption, product, hashtags_raw.split())
            success = post_photo(image_path, caption)
            if success:
                db.history_add(image_path, caption, product)
                db.analytics_increment("generated")
                db.analytics_increment("posts")
                save_last_post()
                print(f"Posted: {product}")
            else:
                db.queue_push(image_path, caption, product)
                print("Post failed, queued")
        except KeyboardInterrupt:
            print("\nScheduler stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)
