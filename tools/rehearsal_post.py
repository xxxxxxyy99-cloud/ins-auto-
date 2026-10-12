"""Full posting rehearsal that never publishes.

Walks the exact production path from bot.post_photo — desktop layout,
create dialog, upload, 继续, 继续, caption (with hashtags, reproducing
the suggestion dropdown) — and stops right before clicking Share, so
nothing is ever posted to Instagram.

Usage:
    python tools/rehearsal_post.py
"""

import glob
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from ins账号自动化.bot import (_new_browser, _wait_for_any, _type_caption,
                               _find_new_post_button, _find_share_button,
                               _dismiss_dialogs, NEXT_BUTTON_SELECTORS)


def main() -> int:
    imgs = glob.glob(str(ROOT / "generated_images" / "*.jpg"))
    if not imgs:
        print("no generated images found")
        return 1
    img = max(imgs, key=os.path.getmtime)
    print("test image:", img)

    pw = b = p = None
    try:
        pw, b, ctx, p = _new_browser(headless=False)
        _dismiss_dialogs(p)
        btn, sel = _find_new_post_button(p)
        print("create btn:", bool(btn), sel)
        if not btn:
            print("REHEARSAL: feed did not load far enough")
            return 1

        try:
            btn.click(timeout=8000)
        except Exception:
            _dismiss_dialogs(p)
            btn.click(timeout=15000)

        fi = p.locator('input[type="file"]')
        deadline = time.time() + 60
        while time.time() < deadline and fi.count() == 0:
            time.sleep(1)
        if fi.count() == 0:
            print("REHEARSAL: no file input found")
            return 1
        fi.first.set_input_files(img)
        print("uploaded")

        nb = _wait_for_any(p, NEXT_BUTTON_SELECTORS, timeout_s=90)
        print("next1:", bool(nb))
        if nb:
            try:
                nb.click(timeout=10000)
            except Exception:
                nb.click(force=True, timeout=5000)
            time.sleep(2)
            nb2 = _wait_for_any(p, NEXT_BUTTON_SELECTORS, timeout_s=45)
            print("next2:", bool(nb2))
            if nb2:
                try:
                    nb2.click(timeout=10000)
                except Exception:
                    nb2.click(force=True, timeout=5000)
                time.sleep(3)

        cb = _wait_for_any(p, ['div[role="textbox"]'], timeout_s=15)
        print("caption box:", bool(cb))
        if cb:
            _type_caption(p, cb, "Rehearsal caption 彩排文案 #icemachine #制冰机 #homebar #kitchengadgets")
            time.sleep(1.5)

        t0 = time.time()
        sb = None
        while time.time() - t0 < 60 and not sb:
            sb = _find_share_button(p)
            if not sb:
                time.sleep(2)
        bb = sb.bounding_box() if sb else None
        pos = (round(bb["x"]), round(bb["y"])) if bb else None
        print(f"share finder: {bool(sb)} after {time.time()-t0:.0f}s | pos: {pos}")
        print("REHEARSAL DONE - nothing published")
        return 0 if sb else 1
    except Exception as e:
        print("REHEARSAL ERROR:", str(e)[:300])
        return 1
    finally:
        try:
            if b:
                b.close()
        except Exception:
            pass
        try:
            if pw:
                pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
