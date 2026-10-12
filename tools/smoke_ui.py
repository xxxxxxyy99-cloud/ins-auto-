"""Headless UI smoke test for the Streamlit dashboard.

Boots app.py on a free port, drives a headless Chromium through every
page (offline mode, no posting, no generation), and checks the rendered
text for Python exception markers.

Usage:
    python tools/smoke_ui.py
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "debug_smoke_streamlit.log"
SHOT = ROOT / "debug_smoke_ui.png"

PAGES = ["内容工作室", "草稿箱", "审核中心", "素材库", "内容管理",
         "发布记录", "数据统计", "设置", "Dashboard"]
MARKERS = ["Traceback", "KeyError", "AttributeError", "TypeError",
           "NameError", "ValueError", "IndexError", "ModuleNotFoundError",
           "StreamlitAPIException", "ImportError", "SyntaxError"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(port: int, timeout: float = 45) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(1)
    return False


def main() -> int:
    port = _free_port()
    log = open(LOG_FILE, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
         "--server.headless=true", "--server.port", str(port),
         "--browser.gatherUsageStats=false"],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)

    failed = 0
    try:
        if not _wait_port(port):
            print("FAIL: streamlit did not start")
            return 1

        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
            page.wait_for_selector("text=InsAuto", timeout=60000)
            time.sleep(3)

            # offline mode (optional — with a saved session the panel
            # may already render in the connected state)
            try:
                page.get_by_role("button", name="离线").first.click(timeout=5000)
                time.sleep(2.5)
            except Exception:
                print("  (already authenticated — skipping the offline toggle)")

            sidebar = page.locator('[data-testid="stSidebar"]')
            for name in PAGES:
                try:
                    sidebar.get_by_role("button", name=name).first.click()
                    time.sleep(2.5)
                    body = page.inner_text("body")
                    bad = [m for m in MARKERS if m in body]
                    if bad:
                        failed += 1
                        print(f"  {name}: BAD -> {','.join(bad)}")
                    else:
                        print(f"  {name}: ok")
                except Exception as e:
                    failed += 1
                    print(f"  {name}: click-fail: {str(e)[:120]}")

            page.screenshot(path=str(SHOT))
            print("screenshot:", SHOT.name)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        log.close()

    print("SMOKE_RESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
