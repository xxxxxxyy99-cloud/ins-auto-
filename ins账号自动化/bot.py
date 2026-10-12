"""Instagram login, session management, and posting via Playwright."""

import time
import random
from pathlib import Path
from playwright.sync_api import sync_playwright, Page
from .config import IG_USERNAME, IG_PASSWORD, IG_PROXY
from .db import DATA_DIR

SESSION_FILE = DATA_DIR / "ig_session.json"


# ═══════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════

def _human_delay(label: str = "", min_s: float = 1, max_s: float = 4):
    """Simulate human pause between actions."""
    delay = random.uniform(min_s, max_s)
    print(f"  [{label}] waiting {delay:.1f}s...")
    time.sleep(delay)


# ═══════════════════════════════════════════════════════════
#  Login
# ═══════════════════════════════════════════════════════════

# Desktop layout: posting exists only in the desktop web UI. The mobile
# web layout has no post button (its plus icon opens the story composer
# and the page nudges "use the app").
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

INSTAGRAM_URL = "https://www.instagram.com"


def _is_logged_in(page: Page) -> bool:
    """Check if the current page is logged into Instagram (language-agnostic).

    Negative checks run first: the logged-out login view also contains
    /accounts/ links (forgot password, sign up), which previously caused
    false positives and made a dead session look valid.
    """
    try:
        url = page.url or ""

        # Auth / challenge pages are never logged in
        if any(bad in url for bad in ("/accounts/login", "/accounts/emailsignup",
                                      "/accounts/password", "/challenge",
                                      "/accounts/suspended")):
            return False

        # Login form on screen → definitely NOT logged in
        for sel in ('input[name="username"]', 'input[name="password"]',
                    'input[type="password"]', 'a[href*="password/reset"]'):
            if page.query_selector(sel) is not None:
                return False
        login_btn = page.query_selector('button[type="submit"]')
        if login_btn:
            text = (login_btn.text_content() or "").lower()
            if "log in" in text or "登录" in text or "ログイン" in text:
                return False

        # Signal 2: SVG navigation icons (language-agnostic)
        svgs = page.query_selector_all('svg[aria-label]')
        labels = [s.get_attribute('aria-label') for s in svgs if s.get_attribute('aria-label')]
        nav_markers = {'Home', 'New post', 'Reels', 'Messages', 'Search',
                       '首页', '加号图标', '探索', '消息', '通知',
                       'ホーム', '新規投稿', '検索', 'メッセージ',
                       'Inicio', 'Nueva publicacion', 'Explorar', 'Mensajes',
                       'Accueil', 'Nouvelle publication', 'Explorer', 'Messages'}
        if set(labels) & nav_markers:
            return True

        # Signal 3: Profile link — but never an auth link
        for a in page.query_selector_all('a[href*="/accounts/"]'):
            href = (a.get_attribute("href") or "").lower()
            if not any(k in href for k in ("login", "password", "signup",
                                           "emailsignup", "register")):
                return True

        # Signal 4: Feed-specific elements
        for text_sel in ['span:has-text("Following")', 'span:has-text("For you")',
                         'span:has-text("关注")', 'span:has-text("推荐")',
                         'span:has-text("你的快拍")', 'span:has-text("快拍")',
                         'span:has-text("Your story")']:
            if page.query_selector(text_sel):
                return True

        # Signal 5: Post-login URL patterns
        if any(ind in url for ind in ['/direct/', '/stories/', '/explore/']):
            return True

        return False
    except Exception:
        return False


def login(
    username: str | None = None,
    password: str | None = None,
    sessionid: str | None = None,
    interactive: bool = True,
) -> bool:
    """
    Login to Instagram via Playwright browser.

    Args:
        username: Instagram username (defaults to IG_USERNAME from config)
        password: Instagram password (defaults to IG_PASSWORD from config)
        sessionid: Kept for backward compat (not used with Playwright).
        interactive: If True, opens browser for manual login when session expired.
                     If False, only tries silent restore (raises on failure).

    Returns:
        True if login succeeded.
    """
    user = username or IG_USERNAME
    pwd = password or IG_PASSWORD

    pw = sync_playwright().start()

    browser = None
    context = None
    page = None

    # ── Route A: restore saved session (silent) ──
    if SESSION_FILE.exists():
        print("Restoring saved session...")
        try:
            browser = _launch(pw, headless=False)
            context = browser.new_context(
                storage_state=str(SESSION_FILE),
                user_agent=DESKTOP_USER_AGENT,
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            if not _goto(page, INSTAGRAM_URL):
                # Network problem — keep the session file, it is not invalid
                browser.close()
                pw.stop()
                raise Exception(NETWORK_HINT)
            time.sleep(3)

            if _is_logged_in(page):
                # Re-save session so mtime is fresh (Streamlit login detect needs this)
                context.storage_state(path=str(SESSION_FILE))
                print(f"Session restored — logged in as @{user}")
                browser.close()
                pw.stop()
                return True

            # Page loaded and we are logged out: session really expired.
            # Keep this window open and continue with the manual login here.
            print("Saved session expired — continuing with manual login in this window.")
            SESSION_FILE.unlink(missing_ok=True)
            try:
                context.clear_cookies()
            except Exception:
                pass
        except Exception as e:
            print(f"Session restore failed: {e}")
            try:
                browser.close()
            except Exception:
                pass
            browser = context = page = None
            if NETWORK_HINT in str(e):
                raise

    # ── Route B: interactive session expired or first-time login ──
    if not interactive:
        try:
            browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass
        raise Exception(
            "Session expired and not in interactive mode. "
            "Please log in manually through the Streamlit dashboard first."
        )

    # ── Manual login: open browser, auto-detect when user logs in ──
    print()
    print("=" * 50)
    print("  Browser will open. Log in to Instagram.")
    print("  Login will be auto-detected — no need to press anything.")
    print("=" * 50)
    print()

    if page is None:
        browser = _launch(pw, headless=False)
        context = browser.new_context(
            user_agent=DESKTOP_USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
    if not _goto(page, f"{INSTAGRAM_URL}/accounts/login/"):
        try:
            page.screenshot(path=str(DATA_DIR / "login_network_fail.png"))
        except Exception:
            pass
        browser.close()
        pw.stop()
        raise Exception(NETWORK_HINT)

    # Wait for the user to log in. Never navigate while a login or
    # challenge form is on screen — that would wipe what the user typed.
    print("  Waiting for login (up to 10 minutes)...", flush=True)
    logged_in = False
    last_check_url = ""
    for i in range(600):
        time.sleep(1)
        try:
            if page.is_closed():
                print("  Browser window was closed before login was completed.")
                break
            if _has_session_cookie(context):
                # Auth cookie exists: login succeeded even if the page
                # itself is slow to render. Save immediately.
                logged_in = True
                print(f"  Login detected after {i}s (session cookie)")
                try:
                    context.storage_state(path=str(SESSION_FILE))
                    print("  Session saved.")
                except Exception as e:
                    print(f"  Session save failed: {e}")
                break
            if _is_logged_in(page):
                logged_in = True
                print(f"  Login detected after {i}s")
                break

            url = page.url
            on_auth_page = ("accounts/login" in url) or ("challenge" in url)

            if not on_auth_page and (url != last_check_url or i % 5 == 0):
                # The user navigated away from the login form — verify session
                try:
                    page.goto(INSTAGRAM_URL, wait_until="domcontentloaded", timeout=15000)
                    time.sleep(2)
                except Exception:
                    pass
                last_check_url = page.url
                if _is_logged_in(page):
                    logged_in = True
                    print(f"  Login detected after {i}s (redirect: {url[:80]})")
                    break

            if i > 0 and i % 30 == 0:
                print(f"  [{i}s] Still waiting for login... (page: {url[:80]})")
        except Exception:
            pass
    print()

    if not logged_in:
        try:
            page.screenshot(path=str(DATA_DIR / "login_timeout.png"))
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
        pw.stop()
        raise Exception(
            "Login was not completed (browser window closed or timed out after 10 minutes). "
            f"Screenshot (if any): {DATA_DIR / 'login_timeout.png'}"
        )

    # Save session
    context.storage_state(path=str(SESSION_FILE))
    print(f"Session saved to {SESSION_FILE.name}")
    browser.close()
    pw.stop()
    print(f"Logged in as @{user}")
    return True


# ═══════════════════════════════════════════════════════════
#  Posting (manual / assisted — single attempt)
#  Each call creates a fresh browser to avoid thread conflicts.
# ═══════════════════════════════════════════════════════════

BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
]

NETWORK_HINT = (
    "无法访问 instagram.com（网络超时）。请确认代理/VPN 已开启；"
    "程序会自动跟随 Windows 系统代理，也可以在 ins账号自动化/data/.env 里"
    "设置 IG_PROXY=http://127.0.0.1:7890（换成你的代理端口）"
)


def _launch(pw, headless: bool):
    """Launch Chromium, honoring IG_PROXY (env override or system proxy).

    Playwright's Chromium does not reliably follow the Windows system
    proxy, so a running local proxy/VPN can silently not apply and
    instagram.com then times out."""
    kwargs = dict(headless=headless, args=BROWSER_ARGS)
    if IG_PROXY:
        kwargs["proxy"] = {"server": IG_PROXY}
        print(f"  [browser] using proxy {IG_PROXY}")
    return pw.chromium.launch(**kwargs)


def _goto(page: Page, url: str, attempts: int = 2, timeout_ms: int = 60000) -> bool:
    """Navigate with retries; returns False on persistent network failure."""
    for i in range(1, attempts + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            return True
        except Exception as e:
            print(f"  Navigation attempt {i}/{attempts} failed: {str(e)[:120]}")
            time.sleep(2)
    return False


def _wait_body(page: Page, timeout_s: int = 20) -> bool:
    """Wait until the page has rendered visible content."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if len((page.inner_text("body") or "").strip()) > 50:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _has_session_cookie(context) -> bool:
    """True when Instagram's auth cookie exists.

    The login response sets the sessionid cookie regardless of whether
    the page itself renders, so this is the most reliable success signal
    on a flaky network."""
    try:
        for c in context.cookies():
            if c.get("name") == "sessionid" and (c.get("value") or "").strip():
                return True
    except Exception:
        return False
    return False


def _wait_for_any(page: Page, selectors, timeout_s: float = 30):
    """Return the first visible matching element, or None after timeout."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    return el
            except Exception:
                continue
        time.sleep(1)
    return None


NEW_POST_SELECTORS = [
    'svg[aria-label="New post"]',
    'svg[aria-label="New Post"]',
    'a[href="/create/select/"]',
    'svg[aria-label="新帖子"]',
    'svg[aria-label="新貼文"]',
    'svg[aria-label="加号图标"]',
    'svg[aria-label="新規投稿"]',
]


def _find_new_post_button(page: Page):
    """Return (element, selector) for the create button (desktop layout)."""
    for sel in NEW_POST_SELECTORS:
        for el in page.query_selector_all(sel):
            try:
                if el.is_visible():
                    return el, sel
            except Exception:
                continue
    return None, None


def _dismiss_dialogs(page: Page):
    """Dismiss Instagram interstitials (notifications prompt etc.) that
    intercept pointer events over the feed. Never call this while the
    create dialog is open — Escape would close it too."""
    for _ in range(2):
        clicked = False
        for sel in ['button:has-text("以后再说")', 'button:has-text("以後再說")',
                    'button:has-text("稍后再说")', 'button:has-text("稍後再說")',
                    'button:has-text("暂时不要")',
                    'button:has-text("Not Now")', 'div[role="button"]:has-text("Not Now")',
                    'button:has-text("暂不")', 'div[role="button"]:has-text("暂不")',
                    'button:has-text("现在不要")', 'button:has-text("現在不要")']:
            try:
                b = page.query_selector(sel)
                if b and b.is_visible():
                    b.click()
                    clicked = True
                    time.sleep(1)
            except Exception:
                continue
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        time.sleep(0.5)
        if not clicked:
            break


def _new_browser(headless: bool = False):
    """Create a fresh browser + context with saved session. Caller must close."""
    pw = sync_playwright().start()
    browser = _launch(pw, headless)
    ctx_kwargs = dict(
        user_agent=DESKTOP_USER_AGENT,
        viewport={"width": 1280, "height": 900},
    )
    if SESSION_FILE.exists():
        ctx_kwargs["storage_state"] = str(SESSION_FILE)
    context = browser.new_context(**ctx_kwargs)
    page = context.new_page()
    if not _goto(page, INSTAGRAM_URL):
        raise Exception(NETWORK_HINT)
    time.sleep(2)
    if not _wait_body(page, 20):
        if page.query_selector("svg[aria-label]"):
            # app shell present but slow; give the assets more time
            print("  Page still loading (slow network), waiting longer...")
            _wait_body(page, 40)
        else:
            print("  Page stuck on splash, reloading once...")
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            _wait_body(page, 25)
    _dismiss_dialogs(page)
    try:
        if len((page.inner_text("body") or "").strip()) < 10:
            print("  WARNING: Instagram 页面正文为空，静态资源可能被拦截。若浏览器窗口一直"
                  "停在启动画面（Meta 标志页），请检查代理分流规则：让 *.cdninstagram.com 和 "
                  "*.fbcdn.net 也走代理（可先在 Clash 用全局模式验证）。")
    except Exception:
        pass
    return pw, browser, context, page


NEXT_BUTTON_SELECTORS = [
    'div[role="dialog"] [aria-label="下一步"]',
    'div[role="dialog"] button:has-text("下一步")',
    'div[role="dialog"] div[role="button"]:has-text("下一步")',
    'div[role="dialog"] [aria-label="Next"]',
    'div[role="dialog"] button:has-text("Next")',
    'div[role="dialog"] div[role="button"]:has-text("Next")',
    'div[role="button"]:has-text("Next")',
    'button:has-text("Next")',
    'div[role="button"]:has-text("下一步")',
    'button:has-text("下一步")',
    'div[role="button"]:has-text("次へ")',
    '[aria-label="Next"]',
    '[aria-label="下一步"]',
]

SHARE_BUTTON_SELECTORS = [
    'div[role="dialog"] div[role="button"]:has-text("Share")',
    'div[role="dialog"] button:has-text("分享")',
    'div[role="dialog"] [aria-label="分享"]',
    'div[role="button"]:has-text("Share")',
    'button:has-text("Share")',
    'div[role="button"]:has-text("共有")',
    'div[role="button"]:has-text("分享")',
    '[aria-label="Share"]',
]

POST_SUCCESS_MARKERS = [
    "Your post has been shared", "Post shared", "已分享", "帖子已分享",
    "你的帖子已分享", "投稿をシェアしました",
]

POST_ERROR_MARKERS = [
    "Something went wrong", "something went wrong", "couldn't share",
    "Couldn't share", "Try Again", "Try again", "无法分享", "再试一次",
]


def _type_caption(page: Page, caption_box, caption: str):
    """Enter the caption quickly: fill() for textareas, insert_text for
    contenteditable boxes. Emoji and newlines work without slow per-char typing."""
    caption_box.click()
    _human_delay("focus_caption", 0.4, 1.2)
    try:
        tag = (caption_box.evaluate("el => el.tagName") or "").upper()
        if tag == "TEXTAREA":
            caption_box.fill(caption)
        else:
            page.keyboard.insert_text(caption)
        print(f"  Caption filled ({len(caption)} chars)")
    except Exception:
        print("  Fast caption entry failed, falling back to typing...")
        for ch in caption:
            caption_box.type(ch, delay=random.randint(40, 120))
        print(f"  Caption typed ({len(caption)} chars)")


def _wait_for_post_result(page: Page, timeout_s: int = 60) -> bool:
    """Wait until Instagram confirms the post or shows an error dialog.

    Returns True when a success marker appears or the share dialog closes
    cleanly; False on a detected error or when nothing can be confirmed.
    """
    deadline = time.time() + timeout_s
    gone_checks = 0
    while time.time() < deadline:
        time.sleep(1.5)
        try:
            for marker in POST_SUCCESS_MARKERS:
                if page.query_selector(f'text={marker}'):
                    try:
                        ok = page.query_selector(
                            'div[role="button"]:has-text("OK"), button:has-text("OK")')
                        if ok and ok.is_visible():
                            ok.click()
                    except Exception:
                        pass
                    return True
            for marker in POST_ERROR_MARKERS:
                if page.query_selector(f'text={marker}'):
                    return False
            if page.query_selector('div[role="dialog"]') is None:
                gone_checks += 1
                if gone_checks >= 2:
                    return True
            else:
                gone_checks = 0
        except Exception:
            continue
    return False


def post_photo(image_path: str, caption: str, headless: bool = False) -> bool:
    """Upload a photo to Instagram and publish it via Playwright browser.

    Creates a fresh browser each call — no shared state across threads.
    """
    if not SESSION_FILE.exists():
        print("Not logged in. Please log in first via the dashboard.")
        return False

    pw = None
    browser = None
    try:
        pw, browser, context, page = _new_browser(headless=headless)

        if not _is_logged_in(page):
            print("Session expired. Please re-login via the dashboard.")
            return False

        # ── Step 1: Click "New post" → handle menu → upload file ──
        _human_delay("pre_new_post", random.uniform(2, 5))

        _dismiss_dialogs(page)
        new_btn, new_post_sel = _find_new_post_button(page)
        if not new_btn:
            raise Exception("New post button not found — are you logged in?")

        # Set up file chooser BEFORE clicking the button. On the desktop
        # layout the create dialog usually opens instead of a chooser, so
        # a short timeout here is expected — the hidden input below handles it.
        try:
            with page.expect_file_chooser(timeout=8000) as fc:
                try:
                    new_btn.click(timeout=8000)
                except Exception:
                    # an overlay (notifications prompt etc.) may intercept
                    print("  Click intercepted, dismissing overlays and retrying...")
                    _dismiss_dialogs(page)
                    new_btn.click(timeout=15000)
                print(f"  Clicked {new_post_sel}")

                # Instagram may show a "Create" menu first
                _human_delay("check_menu", 1, 2)
                for ms in [
                    'div[role="dialog"] div[role="button"]:has-text("Post")',
                    'div[role="dialog"] div[role="button"]:has-text("帖子")',
                ]:
                    mb = page.query_selector(ms)
                    if mb and mb.is_visible():
                        print(f"  Create menu appeared, clicking {ms}")
                        mb.click()
                        break

            fc.value.set_files(image_path)
            print(f"  Uploaded: {image_path}")
        except Exception as e:
            # Desktop create dialog: a hidden file input appears inside it
            # (can take ~15-60s on a slow network), or pick via the button.
            print(f"  No file chooser ({str(e)[:80]}), using the create dialog...")
            fi = page.locator('input[type="file"]')
            deadline = time.time() + 60
            while time.time() < deadline and fi.count() == 0:
                time.sleep(1)
            if fi.count() > 0:
                fi.first.set_input_files(image_path)
                print(f"  Uploaded via hidden input: {image_path}")
            else:
                sel_btn = _wait_for_any(page, [
                    'button:has-text("从电脑中选择")', 'button:has-text("從電腦中選擇")',
                    'button:has-text("Select from computer")',
                    'div[role="button"]:has-text("从电脑中选择")',
                ], timeout_s=15)
                if sel_btn:
                    print("  Clicking 从电脑中选择...")
                    with page.expect_file_chooser(timeout=60000) as fc2:
                        sel_btn.click()
                    fc2.value.set_files(image_path)
                    print(f"  Uploaded: {image_path}")
                else:
                    page.screenshot(path=str(DATA_DIR / "debug_upload_fail.png"))
                    raise Exception("Cannot upload file — no file chooser or input found")

        _human_delay("after_upload", 3, 6)

        # ── Step 2: wait for the editor app, then click "Next" ──
        # The edit screens come from Instagram's JS app; on a slow proxy
        # they can take a long time to appear after the upload starts.
        if not _wait_for_any(page, NEXT_BUTTON_SELECTORS, timeout_s=75):
            raise Exception(
                "Instagram 编辑界面未加载（网络过慢）。请确认代理节点速度正常后重试，"
                "或到你的代理里切换一个更快的节点。")
        for step_label in ["crop", "filter"]:
            _human_delay(f"{step_label}_screen", 1, 2)
            btn = _wait_for_any(page, NEXT_BUTTON_SELECTORS, timeout_s=40)
            if btn:
                try:
                    btn.click()
                    print(f"  Clicked Next ({step_label})")
                except Exception as e:
                    print(f"  Next click failed ({step_label}): {str(e)[:80]}")
            else:
                print(f"  Next button not found on {step_label} screen (may be skipped)")

        # ── Step 3: Type caption ──
        _human_delay("caption_screen", 2, 4)
        caption_selectors = [
            'textarea[aria-label="Write a caption..."]',
            'textarea[placeholder="Write a caption..."]',
            'textarea[aria-label="キャプションを入力..."]',
            'textarea[aria-label="输入说明文字..."]',
            '[aria-label*="说明文字"]',
            'div[role="textbox"]',
        ]
        caption_box = None
        for sel in caption_selectors:
            try:
                caption_box = page.wait_for_selector(sel, timeout=15000)
                if caption_box:
                    print(f"  Found caption input: {sel}")
                    break
            except Exception:
                continue

        if caption_box:
            _type_caption(page, caption_box, caption)
        else:
            print("  WARNING: Caption box not found, posting without caption")

        _human_delay("before_share", 2, 4)

        # ── Step 4: Click Share ──
        share_clicked = False
        for sel in SHARE_BUTTON_SELECTORS:
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

        # ── Step 5: Wait for Instagram to confirm the post ──
        print("  Waiting for Instagram to confirm the post...")
        if _wait_for_post_result(page):
            print(f"  Posted: {Path(image_path).name}")
            return True
        print("  Could not confirm the post was shared — check Instagram manually.")
        try:
            page.screenshot(path=str(DATA_DIR / "post_unconfirmed.png"))
        except Exception:
            pass
        return False

    except Exception as e:
        err = str(e)
        if "challenge" in err.lower() or "checkpoint" in err.lower():
            print(f"  Instagram requires human verification. Complete it in the browser, then try again.")

        print(f"  Post failed: {err[:200]}")
        try:
            page.screenshot(path=str(DATA_DIR / "post_error.png"))
            print(f"  Screenshot saved: data/post_error.png")
        except Exception:
            pass
        return False
    finally:
        try:
            context.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass


def post_carousel(image_paths: list[str], caption: str, headless: bool = False) -> bool:
    """Upload multiple images as a carousel post. Fresh browser each call."""
    if not SESSION_FILE.exists():
        print("Not logged in. Please log in first via the dashboard.")
        return False

    pw = None
    browser = None
    try:
        pw, browser, context, page = _new_browser(headless=headless)
        if not _is_logged_in(page):
            print("Session expired. Please re-login via the dashboard.")
            return False

        _human_delay("pre_carousel", random.uniform(5, 10))

        new_post_sel = None
        for sel in ['svg[aria-label="New post"]', 'svg[aria-label="New Post"]',
                    'svg[aria-label="加号图标"]', 'svg[aria-label="新規投稿"]']:
            try:
                el = page.wait_for_selector(sel, timeout=8000)
                if el:
                    new_post_sel = sel
                    break
            except Exception:
                continue
        if not new_post_sel:
            raise Exception("New post button not found — are you logged in?")
        page.click(new_post_sel)
        _human_delay("after_new_post", 2, 4)

        file_input = page.wait_for_selector('input[type="file"]', timeout=15000)
        file_input.set_input_files(image_paths)
        print(f"  Uploaded {len(image_paths)} images")
        _human_delay("after_upload_multi", 4, 8)

        for step_label in ["crop", "filter", "arrange"]:
            _human_delay(f"{step_label}_screen", 1, 2)
            for sel in NEXT_BUTTON_SELECTORS:
                try:
                    btn = page.wait_for_selector(sel, timeout=8000)
                    if btn and btn.is_visible():
                        btn.click()
                        print(f"  Clicked Next ({step_label})")
                        break
                except Exception:
                    continue

        _human_delay("caption_screen", 2, 4)
        caption_box = None
        for sel in ['textarea[aria-label="Write a caption..."]',
                    'textarea[placeholder="Write a caption..."]',
                    'textarea[aria-label="输入说明文字..."]',
                    'div[role="textbox"]']:
            try:
                caption_box = page.wait_for_selector(sel, timeout=8000)
                if caption_box:
                    break
            except Exception:
                continue
        if caption_box:
            _type_caption(page, caption_box, caption)
        else:
            print("  WARNING: Caption box not found, posting without caption")

        _human_delay("before_share", 2, 4)

        share_clicked = False
        for sel in SHARE_BUTTON_SELECTORS:
            try:
                btn = page.wait_for_selector(sel, timeout=5000)
                if btn and btn.is_visible():
                    btn.click()
                    share_clicked = True
                    print(f"  Clicked Share: {sel}")
                    break
            except Exception:
                continue

        if not share_clicked:
            raise Exception("Share button not found or not clickable")

        print("  Waiting for Instagram to confirm the carousel post...")
        if _wait_for_post_result(page):
            print(f"  Carousel posted: {len(image_paths)} images")
            return True
        print("  Could not confirm the carousel was shared — check Instagram manually.")
        return False

    except Exception as e:
        print(f"  Carousel failed: {e}")
        return False
    finally:
        try:
            context.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass
