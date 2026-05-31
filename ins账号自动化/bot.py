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
    """Check if the current page is logged into Instagram."""
    try:
        has_create = page.query_selector('svg[aria-label="New post"]') is not None
        has_home = page.query_selector('svg[aria-label="Home"]') is not None
        on_login = page.query_selector('input[name="username"]') is not None
        return (has_create or has_home) and not on_login
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
) -> InstaClient:
    """
    Login to Instagram via Playwright browser.

    Routes (in priority order):
      A. Saved Playwright session file  → restore cookies, verify
      B. Username + password            → fill login form, submit
      C. No credentials                 → raise error
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

    # ── Route A: restore saved session ──
    if SESSION_FILE.exists():
        print("Restoring saved session...")
        try:
            browser = pw.chromium.launch_persistent_context(
                user_data_dir=str(DATA_DIR / "browser_profile"),
                headless=False,
                args=browser_args,
                user_agent=MOBILE_USER_AGENT,
                viewport={"width": 412, "height": 915},
                device_scale_factor=2,
                storage_state=str(SESSION_FILE),
            )
            page = browser.new_page()
            page.goto(INSTAGRAM_URL, wait_until="domcontentloaded", timeout=30000)
            _human_delay("page_load", 2, 4)

            if _is_logged_in(page):
                # Persistent context wraps browser + context in one object
                client = InstaClient(browser, browser, page)
                _cl = client
                print(f"Session restored — logged in as @{user}")
                return client

            print("Saved session expired, logging in fresh...")
            browser.close()
        except Exception as e:
            print(f"Session restore failed: {e}")
            try:
                browser.close()
            except Exception:
                pass
            SESSION_FILE.unlink(missing_ok=True)

    # ── Route B: username + password login ──
    if not pwd or pwd == "your-instagram-password":
        raise Exception(
            "No saved session and no password configured.\n"
            "请先通过 Streamlit 界面登录一次，或编辑 data/.env 设置 IG_USERNAME 和 IG_PASSWORD"
        )

    # ── Manual login: open browser, user logs in themselves ──
    print("Opening Instagram for manual login...")
    print("Please log in yourself. The browser will stay open.")
    print("When you see your Instagram feed, press Enter here to save session.")
    print()

    browser = pw.chromium.launch_persistent_context(
        user_data_dir=str(DATA_DIR / "browser_profile"),
        headless=False,
        args=browser_args,
        user_agent=MOBILE_USER_AGENT,
        viewport={"width": 412, "height": 915},
        device_scale_factor=2,
    )
    page = browser.new_page()
    page.goto(f"{INSTAGRAM_URL}/accounts/login/", wait_until="domcontentloaded", timeout=30000)

    # Wait for user to complete login manually
    try:
        input(">>> Press Enter after you've logged in to Instagram... ")
    except (EOFError, KeyboardInterrupt):
        pass

    # Verify login succeeded
    if not _is_logged_in(page):
        browser.close()
        raise Exception("Login not detected. Please try again.")

    # Save session
    browser.storage_state(path=str(SESSION_FILE))
    print(f"Session saved to {SESSION_FILE.name}")
    _save_sessionid_to_db(sessionid if sessionid else "")

    client = InstaClient(browser, browser, page)
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
    """Try to restore saved session silently. No manual login."""
    global _cl
    if not SESSION_FILE.exists():
        return False
    print("Reconnecting from saved session...")
    try:
        login()  # Will use Route A (saved session) since SESSION_FILE exists
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

            # Human warmup before posting
            _warmup_session()

            # Random delay before clicking "post"
            _human_delay("pre_post", random.uniform(3, 8))

            result = _cl.photo_upload(image_path, caption)
            print(f"Posted: {image_path}")

            # Cool-down after posting
            _human_delay("cooldown", random.uniform(5, 15))

            return bool(result)

        except Exception as e:
            err = str(e)

            if "feedback_required" in err:
                # Heavy rate limit — wait a long time
                wait_minutes = random.randint(30, 120)
                print(f"  Rate limited! Waiting {wait_minutes} minutes...")
                time.sleep(wait_minutes * 60)
                SESSION_FILE.unlink(missing_ok=True)
                continue

            if "login_required" in err:
                print(f"  Session expired (attempt {attempt+1}/3): {err[:80]}")
                SESSION_FILE.unlink(missing_ok=True)
                time.sleep(_jitter(10 * (attempt + 1), 0.5))
                continue

            if "challenge_required" in err:
                print(f"  Challenge required — account needs manual verification: {err[:100]}")
                return False

            print(f"  Post failed: {err[:120]}")
            return False

    return False


def post_carousel(image_paths: list[str], caption: str) -> bool:
    global _cl
    if _cl is None:
        print("Not logged in, cannot post")
        return False

    _warmup_session()
    _human_delay("pre_carousel", random.uniform(5, 10))

    try:
        result = _cl.album_upload(image_paths, caption)
        print(f"Carousel posted with {len(image_paths)} images")
        _human_delay("cooldown", random.uniform(8, 20))
        return bool(result)
    except Exception as e:
        print(f"Carousel failed: {e}")
        return False
