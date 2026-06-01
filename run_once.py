"""One-shot post: login → generate → post.  Double-click 一键发文.bat or run: python run_once.py"""
import sys, io, os, time, random, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright
from ins账号自动化.content import generate_prompt, generate_image, generate_caption, build_caption
from ins账号自动化.db import init_db, settings_get, queue_push, history_add, analytics_increment, log_event, DATA_DIR

init_db()
SESSION_FILE = DATA_DIR / "ig_session.json"
IG_URL = "https://www.instagram.com"
ARGS = ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]


def detect_login(page):
    """Return True if Instagram page shows logged-in UI."""
    try:
        url = page.url
        url_ok = "login" not in url and "challenge" not in url
        if not url_ok:
            return False
        # Try each check individually to survive navigation
        has_nav = _safe_qs(page, 'a[href="/"]')
        has_create = _safe_qs(page, 'svg[aria-label="New post"]') or \
                     _safe_qs(page, 'svg[aria-label="加号图标"]') or \
                     _safe_qs(page, '[aria-label="Create"]')
        has_notif = _safe_qs(page, 'svg[aria-label="通知"]') or \
                    _safe_qs(page, 'svg[aria-label="Notifications"]')
        on_login = _safe_qs(page, 'input[name="username"]')
        return (has_nav or has_create or has_notif) and not on_login
    except Exception:
        return False


def _safe_qs(page, sel):
    """query_selector that returns False on any error."""
    try:
        return page.query_selector(sel) is not None
    except Exception:
        return False


def launch_browser(pw, use_session=False):
    """Launch browser — prefer system Chrome for real fingerprint."""
    ctx_kwargs = dict(viewport={"width": 1280, "height": 900})
    if use_session and SESSION_FILE.exists():
        ctx_kwargs["storage_state"] = str(SESSION_FILE)

    # Chrome paths to try (in order of preference)
    chrome_paths = [
        {"channel": "chrome"},
        {"executable_path": "C:/Program Files/Google/Chrome/Application/chrome.exe"},
        {"executable_path": "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"},
        {"executable_path": os.path.expanduser("~/AppData/Local/Google/Chrome/Application/chrome.exe")},
        {},  # fallback: Playwright Chromium
    ]

    for opts in chrome_paths:
        try:
            launch_args = dict(headless=False, args=ARGS, **opts)
            browser = pw.chromium.launch(**launch_args)
            ctx = browser.new_context(**ctx_kwargs)
            page = ctx.new_page()
            label = opts.get("channel") or opts.get("executable_path") or "chromium"
            print(f"  Browser: {label}")
            return browser, ctx, page
        except Exception:
            continue

    raise Exception("Cannot launch any browser")


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 50)
    print("  InsAuto — One-Shot Post")
    print("=" * 50)

    pw = sync_playwright().start()

    # ─── LOGIN ───
    if SESSION_FILE.exists():
        browser, ctx, page = launch_browser(pw, use_session=True)
        page.goto(IG_URL, wait_until="networkidle", timeout=30000)
        time.sleep(3)
    else:
        print("\n>>> First-time login required.")
        print(">>> System Chrome opens. Log in ONCE.")
        print(">>> Session saved. Next run auto-login.\n")
        browser, ctx, page = launch_browser(pw, use_session=False)

    if not detect_login(page):
        page.goto(f"{IG_URL}/accounts/login/", wait_until="networkidle", timeout=30000)
        time.sleep(2)
        print(f"  Login page: {page.url}")
        print("  Log in now. Auto-detection active...")

        for i in range(300):
            time.sleep(1)
            try:
                if detect_login(page):
                    ctx.storage_state(path=str(SESSION_FILE))
                    print(f"\n  Session saved! ({i}s)")
                    break
            except Exception:
                pass
            if i % 60 == 0 and i > 0:
                try:
                    page.goto(IG_URL, wait_until="networkidle", timeout=10000)
                except:
                    pass
                print(f"  [{i}s] URL={page.url[:80]}")
        else:
            print("\n  Login timed out.")
            browser.close(); pw.stop(); sys.exit(1)
    else:
        # Already logged in from session
        print("  Auto-login successful!")
        if not SESSION_FILE.exists():
            ctx.storage_state(path=str(SESSION_FILE))

    # ─── GENERATE ───
    print("\n--- Generating content ---")
    s = settings_get()
    prompt, product = generate_prompt(niche=s.get("niche", ""))
    img = generate_image(prompt, model=s.get("image_model") or None)
    if not img:
        print("Image generation FAILED"); pw.stop(); sys.exit(1)
    cap = generate_caption(product, style=s.get("style", "casual"),
                           niche=s.get("audience", ""),
                           model=s.get("llm_model", "qwen/qwen-2.5-7b-instruct"),
                           instructions=s.get("caption_instructions", ""))
    hashtags = s.get("hashtags", "")
    if hashtags.strip():
        cap = build_caption(cap, hashtags.split())
    print(f"  Product: {product}")
    print(f"  Image:   {img}")
    print(f"  Caption: {cap[:80]}...")

    # ─── POST ───
    print("\n--- Posting ---")
    try:
        # 1. Navigate home
        page.goto(IG_URL, wait_until="networkidle", timeout=30000)
        time.sleep(2)
        print("[1] On home page")

        # 2. Navigate to create page
        print("[2] Opening create page...")
        page.goto(f"{IG_URL}/create/select/", wait_until="networkidle", timeout=20000)
        time.sleep(3)
        page.screenshot(path=str(DATA_DIR / "step1_create.png"))
        print(f"  URL: {page.url}")

        # 3. Upload file
        print("[3] Uploading...")
        try:
            with page.expect_file_chooser(timeout=15000) as fc:
                # Click any upload trigger
                for s in ['button:has-text("Select from computer")',
                          'span:has-text("Select from computer")',
                          'text=Select from computer',
                          'input[type="file"]']:
                    el = page.query_selector(s)
                    if el:
                        el.click(); break
                else:
                    # Maybe file input is visible
                    pass
            fc.value.set_files(img)
            print(f"  Uploaded: {Path(img).name}")
        except Exception as e:
            print(f"  File chooser: {e}")
            fi = page.locator('input[type="file"]')
            if fi.count() > 0:
                fi.first.set_input_files(img)
                print(f"  Uploaded via hidden input")
            else:
                raise Exception("Upload failed")

        time.sleep(3)
        page.screenshot(path=str(DATA_DIR / "step2_uploaded.png"))
        print(f"  URL after upload: {page.url}")

        # 4. Edit flow: click Next/Share as they appear
        print("[4] Edit flow...")
        for step in range(5):
            time.sleep(2)
            found = False
            for sel in [
                'div[role="button"]:has-text("Next")',
                'div[role="button"]:has-text("下一步")',
                'button:has-text("Next")',
                'div[role="button"]:has-text("Share")',
                'div[role="button"]:has-text("分享")',
                'button:has-text("Share")',
            ]:
                btn = page.query_selector(sel)
                if btn and btn.is_visible() and btn.is_enabled():
                    btn.click()
                    print(f"  [{step}] Clicked: {sel}")
                    found = True
                    break
            if not found:
                print(f"  [{step}] No button")
                # Check if we're done
                if "instagram.com/p/" in page.url:
                    print("  Post published!")
                    break
                # Check for caption box
                ta = page.query_selector('textarea')
                if ta and ta.is_visible():
                    print("  Found caption textarea")
                    ta.click()
                    time.sleep(0.5)
                    for ch in cap:
                        ta.type(ch, delay=random.randint(60, 150))
                    print(f"  Caption typed ({len(cap)} chars)")
                    # Now look for Share
                    time.sleep(1)
                    for s in ['div[role="button"]:has-text("Share")',
                               'div[role="button"]:has-text("分享")']:
                        b = page.query_selector(s)
                        if b and b.is_visible():
                            b.click()
                            print(f"  Shared!")
                            found = True
                            break

        time.sleep(5)
        page.screenshot(path=str(DATA_DIR / "step3_done.png"))
        print(f"  Final URL: {page.url}")

        if "instagram.com/p/" in page.url or page.query_selector('text="Posted"'):
            print("\n✅ SUCCESS — Post published!")
            queue_push(img, cap, product)
            analytics_increment("generated")
            analytics_increment("posts")
            history_add(img, cap, product)
            log_event("post_success", product=product, message="One-shot post via run_once")
        else:
            print("\n⚠️  Could not confirm post. Check screenshots in data/ folder.")
            print(f"   Final URL: {page.url}")

    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        try:
            page.screenshot(path=str(DATA_DIR / "crash.png"))
            print("  Screenshot saved: data/crash.png")
        except:
            pass
    finally:
        try:
            browser.close()
        except:
            pass
        pw.stop()
    print("Done.")
