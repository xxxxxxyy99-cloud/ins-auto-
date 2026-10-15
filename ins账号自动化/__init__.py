"""ins账号自动化 — Instagram AI content operations assistant."""

from .db import (
    # Assets
    asset_add, asset_get_all, asset_toggle_favorite, asset_delete,
    asset_count, asset_get_by_category,
    # Drafts
    draft_save, draft_get_all, draft_update, draft_delete,
    draft_mark_posted, draft_count,
    draft_submit_review, draft_approve, draft_reject, review_count,
    draft_search,
    # History
    get_history, add_to_history, clear_history,
    # Settings
    get_settings, save_settings,
    # Analytics
    analytics_totals, analytics_overview, analytics_increment,
    # Activity log
    get_recent_activity,
    # Shared helpers
    init_db, log_event,
)

from .content import (
    generate_prompt, generate_image, generate_caption, generate_hashtags,
    build_caption,
    ASPECT_RATIOS, DEFAULT_CATEGORIES, CAPTION_STYLES,
    TOPICS, TOPIC_KEYS,
    IMAGE_DIR, DEFAULT_CAPTION_MODEL,
)
from .logger import get_logger
