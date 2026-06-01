"""Instagram login, session management, and posting via Playwright."""

import time
import random
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from .config import IG_USERNAME, IG_PASSWORD
from .db import DATA_DIR

SESSION_FILE = DATA_DIR / "ig_session.json"


# ═══════════════════════════════════════════════════════════
#  InstaClient — thin wrapper around Playwright browser
# ═══════════════════════════════════════════════════════════

class InstaClient:
    """Wraps Playwright browser + page for Instagram automation."""

    def __init__(self, browser: Browser | BrowserContext, context: BrowserContext, page: Page):
        self.browser = browser
        self.context = context
        self.page = page
        # For persistent context, browser and context are the same object
        self._is_persistent = browser is context

    def __bool__(self) -> bool:
        return self.page is not None and not self.page.is_closed()

    def close(self):
        try:
            self.page.close()
        except Exception:
            pass
        # For persistent context, close the context (which is also the browser)
        try:
            self.context.close()
        except Exception:
            pass
        # Only close browser if it's separate from context
        if not self._is_persistent:
            try:
                self.browser.close()
            except Exception:
                pass


_cl: InstaClient | None = None


# ═══════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════

def _jitter(base: float, pct: float = 0.3) -> float:
    """Add random jitter to a delay to appear more human."""
    return base * (1 + random.uniform(-pct, pct))


def _human_delay(label: str = "", min_s: float = 1, max_s: float = 4):
    """Simulate human pause between actions."""
    delay = random.uniform(min_s, max_s)
    print(f"  [{label}] waiting {delay:.1f}s...")
    time.sleep(delay)


def _human_type(page: Page, selector: str, text: str):
    """Type text one character at a time like a human."""
    for ch in text:
        page.type(selector, ch, delay=random.randint(50, 200))


def _get_stored_sessionid() -> str | None:
    """Retrieve sessionid from DB settings (set during UI login)."""
    try:
        from .db import settings_get
        s = settings_get()
        sid = s.get("ig_sessionid", "").strip()
        if sid:
            return sid
    except Exception:
        pass
    return None


def _save_sessionid_to_db(sessionid: str):
    """Persist sessionid to DB so reconnection can use it."""
    try:
        from .db import settings_set
        settings_set(ig_sessionid=sessionid)
        print(f"  SessionID persisted to DB ({len(sessionid)} chars)")
    except Exception as e:
        print(f"  WARNING: Failed to persist sessionid: {e}")


# ═══════════════════════════════════════════════════════════
#  Login
# ═══════════════════════════════════════════════════════════

MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro Build/UQ1A.240205.004; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/122.0.6261.64 "
    "Mobile Safari/537.36"
)

INSTAGRAM_URL = "https://www.instagram.com"


def _is_logged_in(page: Page) -> bool:
    """Check if the current page is logged into Instagram (language-agnostic)."""
    try:
        # Get all SVG aria-labels — Instagram nav only appears when logged in
        svgs = page.query_selector_all('svg[aria-label]')
        labels = [s.get_attribute('aria-label') for s in svgs if s.get_attribute('aria-label')]

        # Instagram logged-in nav has these icons (in any language)
        nav_markers = {'Home', 'New post', 'Reels', 'Messages', 'Search',
                       '首页', '加号图标', '探索', '消息', '通知',
                       'ホーム', '新規投稿', '検索', 'メッセージ',
                       'Inicio', 'Nueva publicacion', 'Explorar', 'Mensajes',
                       'Accueil', 'Nouvelle publication', 'Explorer', 'Messages'}

        has_nav = bool(set(labels) & nav_markers)

        # Not logged in if username/password inputs are visible
        on_login = page.query_selector('input[name="username"]') is not None

        return has_nav and not on_login
    except Exception:
        return False


def _click_if_exists(page: Page, selector: str, timeout: int = 3000):
    """Click an element if it appears within timeout, silently skip if not."""
    try:
        el = page.wait_for_selector(selector, timeout=timeout)
        if el and el.is_visible():
            el.click()
            _human_delay("click", 0.5, 1.5)
    except Exception:
        pass


def _get_text(page: Page, selector: str) -> str | None:
    """Get text content of an element if it exists."""
    try:
        el = page.query_selector(selector)
        if el:
            return el.text_content()
    except Exception:
        pass
    return None


def login(
    username: str | None = None,
    password: str | None = None,
    sessionid: str | None = None,
    interactive: bool = True,
) -> InstaClient:
    """
    Login to Instagram via Playwright browser.

    Args:
        username: Instagram username (defaults to IG_USERNAME from config)
        password: Instagram password (defaults to IG_PASSWORD from config)
        sessionid: Not used in Playwright version (kept for backward compat)
        interactive: If True, opens browser for manual login when session expired.
                     If False, only tries silent restore (raises on failure).

    Returns:
        InstaClient wrapping browser + page.
    """
    global _cl

    user = username or IG_USERNAME
    pwd = password or IG_PASSWORD

    # Close any existing client
    if _cl is not None:
        try:
            _cl.close()
        except Exception:
            pass
        _cl = None

    pw = sync_playwright().start()
    browser_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
    ]

    # ── Route A: restore saved session (silent) ──
    if SESSION_FILE.exists():
        print("Restoring saved session...")
        try:
            browser = pw.chromium.launch(headless=False, args=browser_args)
            context = browser.new_context(
                storage_state=str(SESSION_FILE),
                user_agent=MOBILE_USER_AGENT,
                viewport={"width": 412, "height": 915},
                device_scale_factor=2,
            )
            page = context.new_page()
            page.goto(INSTAGRAM_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            if _is_logged_in(page):
                client = InstaClient(browser, context, page)
                _cl = client
                print(f"Session restored — logged in as @{user}")
                return client

            print("Saved session expired, need manual login.")
            browser.close()
        except Exception as e:
            print(f"Session restore failed: {e}")
            try:
                browser.close()
            except Exception:
                pass
            SESSION_FILE.unlink(missing_ok=True)

    # ── Route B: interactive session expired or first-time login ──
    if not interactive:
        raise Exception(
            "Session expired and not in interactive mode. "
            "Please log in manually through the Streamlit dashboard first."
        )

    if not pwd or pwd == "your-instagram-password":
        raise Exception(
            "No saved session and no password configured.\n"
            "请先通过 Streamlit 界面登录一次，或编辑 data/.env 设置 IG_USERNAME 和 IG_PASSWORD"
        )

    # ── Manual login: open browser, auto-detect when user logs in ──
    print()
    print("=" * 50)
    print("  Browser will open. Log in to Instagram.")
    print("  Login will be auto-detected — no need to press anything.")
    print("=" * 50)
    print()

    browser = pw.chromium.launch(headless=False, args=browser_args)
    context = browser.new_context(
        user_agent=MOBILE_USER_AGENT,
        viewport={"width": 412, "height": 915},
        device_scale_factor=2,
    )
    page = context.new_page()
    page.goto(f"{INSTAGRAM_URL}/accounts/login/", wait_until="domcontentloaded", timeout=30000)

    # Wait for user to login — poll every 1 second, max 5 minutes
    print("  Waiting for login...", flush=True)
    logged_in = False
    for i in range(300):  # 300 x 1s = 5 min
        time.sleep(1)
        try:
            url = page.url
            # If URL changed from login page, user probably logged in
            if "accounts/login" not in url and "challenge" not in url:
                page.goto(INSTAGRAM_URL, wait_until="networkidle", timeout=8000)
                time.sleep(1)
                if _is_logged_in(page):
                    logged_in = True
                    print(f"  Login detected after {i}s")
                    break
                else:
                    # Not yet — go back to wherever we were
                    print(f"  URL changed but not logged in: {url[:80]}")
        except Exception:
            pass
    print()

    if not logged_in:
        page.screenshot(path=str(DATA_DIR / "login_timeout.png"))
        browser.close()
        raise Exception(
            "Login timed out (5 min). Browser closed. "
            f"Check screenshot: {DATA_DIR / 'login_timeout.png'}"
        )

    # Save session
    context.storage_state(path=str(SESSION_FILE))
    print(f"Session saved to {SESSION_FILE.name}")
    _save_sessionid_to_db(sessionid if sessionid else "")

    client = InstaClient(browser, context, page)
    _cl = client
    print(f"Logged in as @{user}")
    return client


# ═══════════════════════════════════════════════════════════
#  Session management
# ═══════════════════════════════════════════════════════════


def _warmup_session():
    """Simulate human browsing before posting to avoid bot detection."""
    global _cl
    if _cl is None or _cl.page.is_closed():
        return
    try:
        page = _cl.page
        # Scroll feed a few times like a real user
        for i in range(2):
            _human_delay(f"scroll_{i}", random.uniform(2, 5))
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            time.sleep(random.uniform(0.5, 1.5))
    except Exception as e:
        print(f"  Warmup skipped: {e}")


def _reconnect() -> bool:
    """Try to restore saved session silently. Never opens manual login."""
    global _cl
    if not SESSION_FILE.exists():
        return False
    print("Reconnecting from saved session...")
    try:
        login(interactive=False)
        return _cl is not None and bool(_cl)
    except Exception as e:
        print(f"Silent reconnect failed: {e}")
        return False


def _session_healthy() -> bool:
    """Check if current session is still valid via Playwright page."""
    global _cl
    if _cl is None or _cl.page.is_closed():
        return False
    try:
        return _is_logged_in(_cl.page)
    except Exception:
        return False


def post_photo(image_path: str, caption: str) -> bool:
    """Upload a photo to Instagram and publish it via Playwright browser."""
    global _cl
    if _cl is None:
        print("Not logged in, cannot post")
        return False

    for attempt in range(3):
        try:
            # Session check
            if attempt > 0 or not _session_healthy():
                print(f"  Session stale, reconnecting (attempt {attempt+1})...")
                if not _reconnect():
                    print("  Reconnect failed")
                    time.sleep(_jitter(60, 0.3))
                    continue

            page = _cl.page

            # Warmup: scroll feed to appear human
            _warmup_session()

            # ── Step 1-2: Click "New post" → handle menu → upload file ──
            _human_delay("pre_new_post", random.uniform(2, 5))

            new_post_sel = None
            for sel in [
                'svg[aria-label="New post"]', 'svg[aria-label="New Post"]',
                'svg[aria-label="加号图标"]', 'svg[aria-label="新規投稿"]',
            ]:
                el = page.query_selector(sel)
                if el:
                    new_post_sel = sel
                    break

            if not new_post_sel:
                raise Exception("New post button not found")

            # Set up file chooser BEFORE clicking the button
            try:
                with page.expect_file_chooser(timeout=30000) as fc:
                    page.click(new_post_sel)
                    print(f"  Clicked {new_post_sel}, waiting for file chooser...")

                    # Maybe a menu appeared instead of file chooser
                    _human_delay("check_menu", 1, 2)
                    post_menu_sel = None
                    for ms in [
                        'div[role="dialog"] div[role="button"]:has-text("Post")',
                        'div[role="dialog"] div[role="button"]:has-text("帖子")',
                    ]:
                        mb = page.query_selector(ms)
                        if mb and mb.is_visible():
                            post_menu_sel = ms
                            break

                    if post_menu_sel:
                        print(f"  Create menu appeared, clicking {post_menu_sel}")
                        page.click(post_menu_sel)

                fc.value.set_files(image_path)
                print(f"  Uploaded: {image_path}")
            except Exception as e:
                # Fallback: hidden input
                print(f"  File chooser failed ({e}), trying hidden input...")
                fi = page.locator('input[type="file"]')
                if fi.count() > 0:
                    fi.first.set_input_files(image_path)
                    print(f"  Uploaded via hidden input: {image_path}")
                else:
                    page.screenshot(path=str(DATA_DIR / "debug_upload_fail.png"))
                    raise Exception("Cannot upload file — no file chooser or input found")

            _human_delay("after_upload", 3, 6)

            # ── Step 3: Click "Next" through edit screens ──
            for step_label in ["crop", "filter"]:
                _human_delay(f"{step_label}_screen", 1, 2)
                next_clicked = False
                for sel in [
                    'div[role="button"]:has-text("Next")',
                    'button:has-text("Next")',
                    'div[role="button"]:has-text("下一步")',
                    'div[role="button"]:has-text("次へ")',
                    '[aria-label="Next"]',
                ]:
                    try:
                        btn = page.wait_for_selector(sel, timeout=8000)
                        if btn and btn.is_visible():
                            btn.click()
                            next_clicked = True
                            print(f"  Clicked Next ({step_label})")
                            break
                    except Exception:
                        continue
                if not next_clicked:
                    print(f"  Next button not found on {step_label} screen (may be skipped)")

            # ── Step 4: Type caption ──
            _human_delay("caption_screen", 2, 4)
            caption_selectors = [
                'textarea[aria-label="Write a caption..."]',
                'textarea[placeholder="Write a caption..."]',
                'textarea[aria-label="キャプションを入力..."]',
                'textarea[aria-label="输入说明文字..."]',
                'div[role="textbox"]',
            ]
            caption_box = None
            for sel in caption_selectors:
                try:
                    caption_box = page.wait_for_selector(sel, timeout=8000)
                    if caption_box:
                        print(f"  Found caption input: {sel}")
                        break
                except Exception:
                    continue

            if caption_box:
                caption_box.click()
                _human_delay("focus_caption", 0.5, 1.5)
                # Type caption with human-like speed
                for ch in caption:
                    caption_box.type(ch, delay=random.randint(60, 180))
                print(f"  Caption typed ({len(caption)} chars)")
            else:
                print("  WARNING: Caption box not found, posting without caption")

            _human_delay("before_share", 2, 4)

            # ── Step 5: Click Share ──
            share_clicked = False
            for sel in [
                'div[role="button"]:has-text("Share")',
                'button:has-text("Share")',
                'div[role="button"]:has-text("共有")',
                'div[role="button"]:has-text("分享")',
                '[aria-label="Share"]',
            ]:
                try:
                    btn = page.wait_for_selector(sel, timeout=5000)
                    if btn and btn.is_visible() and btn.is_enabled():
                        btn.click()
                        share_clicked = True
                        print(f"  Clicked Share: {sel}")
                        break
                except Exception:
                    continue

            if not share_clicked:
                raise Exception("Share button not found or not clickable")

            # ── Step 6: Wait for post to complete ──
            print("  Waiting for post to complete...")
            _human_delay("posting", 5, 10)

            # Verify: wait for "Post shared" or redirect away from create page
            try:
                page.wait_for_url(f"{INSTAGRAM_URL}/**", timeout=30000)
            except Exception:
                pass  # URL might not change

            # Check we're not still on the create/share page
            still_creating = page.query_selector('div[role="button"]:has-text("Share")')
            if still_creating and still_creating.is_visible():
                # Maybe the post needs one more click
                _human_delay("retry_share", 2, 3)
                try:
                    still_creating.click()
                    _human_delay("posting2", 5, 10)
                except Exception:
                    pass

            print(f"  Posted: {Path(image_path).name}")

            # ── Step 7: Cooldown ──
            _human_delay("cooldown", random.uniform(8, 20))

            return True

        except Exception as e:
            err = str(e)

            if "feedback_required" in err or "rate" in err.lower():
                wait_minutes = random.randint(30, 120)
                print(f"  Rate limited! Waiting {wait_minutes} min...")
                time.sleep(wait_minutes * 60)
                continue

            if "login_required" in err or "login" in err.lower():
                print(f"  Session expired (attempt {attempt+1}/3): {err[:80]}")
                SESSION_FILE.unlink(missing_ok=True)
                time.sleep(_jitter(10 * (attempt + 1), 0.5))
                continue

            if "challenge" in err.lower() or "checkpoint" in err.lower():
                print(f"  Challenge required: {err[:100]}")
                return False

            print(f"  Post failed: {err[:120]}")
            return False

    return False


def post_carousel(image_paths: list[str], caption: str) -> bool:
    """Upload multiple images as a carousel post."""
    global _cl
    if _cl is None:
        print("Not logged in, cannot post")
        return False

    page = _cl.page
    _warmup_session()
    _human_delay("pre_carousel", random.uniform(5, 10))

    try:
        # Click new post
        new_btn = page.wait_for_selector('svg[aria-label="New post"]', timeout=10000)
        new_btn.click()
        _human_delay("after_new_post", 2, 4)

        # Upload all images
        file_input = page.wait_for_selector('input[type="file"]', timeout=15000)
        file_input.set_input_files(image_paths)
        print(f"  Uploaded {len(image_paths)} images")
        _human_delay("after_upload_multi", 4, 8)

        # Click through edit screens
        for step_label in ["crop", "filter", "arrange"]:
            _human_delay(f"{step_label}_screen", 1, 2)
            for sel in ['div[role="button"]:has-text("Next")', 'button:has-text("Next")']:
                try:
                    btn = page.wait_for_selector(sel, timeout=8000)
                    if btn and btn.is_visible():
                        btn.click()
                        print(f"  Clicked Next ({step_label})")
                        break
                except Exception:
                    continue

        # Caption
        _human_delay("caption_screen", 2, 4)
        caption_box = page.wait_for_selector('textarea[aria-label="Write a caption..."]', timeout=10000)
        if caption_box:
            caption_box.click()
            for ch in caption:
                caption_box.type(ch, delay=random.randint(60, 180))
            print(f"  Caption typed ({len(caption)} chars)")

        _human_delay("before_share", 2, 4)

        # Share
        for sel in ['div[role="button"]:has-text("Share")', 'button:has-text("Share")']:
            try:
                btn = page.wait_for_selector(sel, timeout=5000)
                if btn and btn.is_visible():
                    btn.click()
                    print(f"  Clicked Share")
                    break
            except Exception:
                continue

        _human_delay("posting", 5, 10)
        _human_delay("cooldown", random.uniform(8, 20))
        print(f"  Carousel posted: {len(image_paths)} images")
        return True

    except Exception as e:
        print(f"  Carousel failed: {e}")
        return False
