"""Instagram login, session management, and posting via instagrapi."""

import time
import random
from instagrapi import Client
from .config import IG_USERNAME, IG_PASSWORD
from .db import DATA_DIR

SESSION_FILE = DATA_DIR / "ig_session.json"
_cl: Client | None = None


def _jitter(base: float, pct: float = 0.3) -> float:
    """Add random jitter to a delay to appear more human."""
    return base * (1 + random.uniform(-pct, pct))


def _human_delay(label: str = "", min_s: float = 1, max_s: float = 4):
    """Simulate human pause between actions."""
    delay = random.uniform(min_s, max_s)
    print(f"  [{label}] waiting {delay:.1f}s...")
    time.sleep(delay)


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


def _create_client() -> Client:
    """Create client with randomized device profile to avoid fingerprinting."""
    c = Client()

    # Rotate user agents
    agents = [
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro Build/UQ1A.240205.004; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/122.0.6261.64 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.6367.82 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 14; Pixel 7 Build/UQ1A.240205.002; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/121.0.6167.143 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    ]
    c.set_user_agent(random.choice(agents))

    # Vary device slightly
    devices = [
        {"manufacturer": "Google", "model": "Pixel 8 Pro",
         "android_version": 34, "android_release": "14.0",
         "dpi": "420dpi", "resolution": "1080x1920", "chipset": "qcom"},
        {"manufacturer": "Samsung", "model": "SM-S928B",
         "android_version": 34, "android_release": "14.0",
         "dpi": "480dpi", "resolution": "1440x3120", "chipset": "qcom"},
        {"manufacturer": "Google", "model": "Pixel 7",
         "android_version": 34, "android_release": "14.0",
         "dpi": "412dpi", "resolution": "1080x2400", "chipset": "qcom"},
    ]
    c.set_device(random.choice(devices))

    return c


def login(username: str | None = None, password: str | None = None, sessionid: str | None = None) -> Client:
    global _cl
    user = username or IG_USERNAME
    pwd = password or IG_PASSWORD

    if not sessionid:
        sessionid = _get_stored_sessionid()

    # ── Route A: sessionid login ──
    if sessionid:
        raw = sessionid.strip()
        if raw.startswith("sessionid="):
            raw = raw[len("sessionid="):]
        from urllib.parse import unquote
        raw = unquote(raw)
        c = _create_client()
        print("Logging in with sessionid...")
        try:
            c.login_by_sessionid(raw)
            _human_delay("login", 2, 5)
            c.dump_settings(str(SESSION_FILE))
            _save_sessionid_to_db(sessionid.strip())
            _cl = c
            print(f"Logged in as @{user}")
            return _cl
        except Exception as e:
            raise Exception(
                f"SessionID 登录失败: {e}\n\n"
                "可能是 sessionid 已过期，请重新获取:\n"
                "1. 用 Chrome/Edge 打开 Instagram.com 并登录\n"
                "2. 按 F12 → Application → Cookies → instagram.com\n"
                "3. 找到 sessionid，复制完整值粘贴到输入框"
            )

    c = _create_client()

    # ── Route B: saved session ──
    if SESSION_FILE.exists():
        try:
            c.load_settings(str(SESSION_FILE))
            c.login(user, pwd)
            _human_delay("session_load", 2, 4)
            c.get_timeline_feed()
            _cl = c
            print(f"Logged in with saved session: @{user}")
            return _cl
        except Exception as e:
            print(f"Saved session expired: {e}")
            SESSION_FILE.unlink(missing_ok=True)
            c = _create_client()

    # ── Route C: password login ──
    if pwd and pwd != "your-instagram-password":
        print("Logging in with password...")
        try:
            if username:
                from . import config
                config.IG_USERNAME = username
            c.login(user, pwd)
            _human_delay("pwd_login", 3, 6)
            c.get_timeline_feed()
            c.dump_settings(str(SESSION_FILE))
            _cl = c
            print(f"Logged in as @{user}")
            return _cl
        except Exception as e:
            raise Exception(f"密码登录失败: {e}")

    raise Exception(
        "登录失败。请提供有效的 sessionid:\n"
        "1. 用 Chrome/Edge 打开 Instagram.com 并登录\n"
        "2. 按 F12 → Application → Cookies → instagram.com\n"
        "3. 找到 sessionid，复制完整值粘贴到输入框"
    )


def _warmup_session():
    """Simulate human browsing before posting to avoid bot detection."""
    global _cl
    if _cl is None:
        return

    actions = [
        ("scroll_feed", lambda: _cl.get_timeline_feed()),
        ("scroll_feed2", lambda: _cl.get_timeline_feed()),
    ]
    random.shuffle(actions)
    for name, action in actions:
        try:
            _human_delay(name, random.uniform(2, 6))
            action()
        except Exception as e:
            print(f"  Warmup {name} skipped: {e}")


def _reconnect() -> bool:
    """Try to reconnect when session expires."""
    sessionid = _get_stored_sessionid()
    if sessionid:
        print("Reconnecting with stored sessionid...")
        try:
            login(sessionid=sessionid)
            return True
        except Exception as e:
            print(f"Sessionid reconnect failed: {e}")

    pwd = IG_PASSWORD
    if pwd and pwd != "your-instagram-password":
        print("Reconnecting with password...")
        try:
            login(password=pwd)
            return True
        except Exception as e:
            print(f"Password reconnect failed: {e}")

    return False


def _session_healthy() -> bool:
    """Check if current session is still valid."""
    global _cl
    if _cl is None:
        return False
    try:
        _cl.get_timeline_feed()
        return True
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
