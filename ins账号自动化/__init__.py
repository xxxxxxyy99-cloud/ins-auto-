"""ins账号自动化 — AI Instagram content automation package."""

from .db import (
    # Queue
    get_queue, queue_post, queue_remove, queue_clear,
    queue_update_caption, queue_count, pop_queue,
    # History
    get_history, add_to_history, clear_history, history_count,
    # Settings
    get_settings, save_settings,
    # Status / control
    get_status, set_running,
    # Analytics
    analytics_totals, analytics_overview, increment_generated, increment_posted,
    # Activity log
    get_recent_activity,
)

from .content import (
    generate_prompt, generate_image, generate_caption, build_caption,
    generate_batch, ASPECT_RATIOS, DEFAULT_CATEGORIES, CAPTION_STYLES,
    IMAGE_DIR,
)
from .bot import login, post_photo, post_carousel
from .automation import save_last_post, next_post_delay, automation_worker, generate_scheduled_time
from .logger import get_logger
from .state import StateMachine, State
from .cli import generate_and_queue, post_from_queue, generate_and_post, run_scheduler
