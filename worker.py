"""One-shot auto-post worker.

Runs exactly one scheduled-style post (generate + publish) in this
process, then exits. Kept as a separate process so Playwright's sync
API never shares a thread or event loop with Streamlit or Tkinter.

Usage:
    python worker.py            # generate and publish now
    python worker.py --dry-run  # generate only, save as draft, no posting
"""

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DATA_DIR = ROOT / "ins账号自动化" / "data"
LOCK_FILE = DATA_DIR / "post.lock"
LOCK_MAX_AGE_S = 600


def _lock_reason() -> str | None:
    """None when free to post, otherwise the reason it is locked."""
    try:
        if LOCK_FILE.exists():
            age = time.time() - LOCK_FILE.stat().st_mtime
            if age < LOCK_MAX_AGE_S:
                holder = LOCK_FILE.read_text(encoding="utf-8", errors="replace").strip()
                return f"已有发布任务在进行中（{age:.0f} 秒前启动，{holder}）"
    except Exception:
        pass
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="InsAuto one-shot worker")
    parser.add_argument("--dry-run", action="store_true",
                        help="generate and save a draft without publishing")
    args = parser.parse_args()

    reason = _lock_reason()
    if reason:
        print(f"[worker] {reason}")
        return 3

    try:
        LOCK_FILE.parent.mkdir(exist_ok=True)
        LOCK_FILE.write_text(f"pid={os.getpid()}", encoding="utf-8")
    except Exception:
        pass

    try:
        from ins账号自动化.automation import run_auto_post
        result = run_auto_post(dry_run=args.dry_run)
    except Exception as e:
        print(f"[worker] 运行异常: {e}")
        return 2
    finally:
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    stage = result.get("stage")
    if result.get("ok"):
        if stage == "dry_run":
            print(f"[worker] 演示完成: {result.get('product')} -> {result.get('image')}")
        else:
            print(f"[worker] 发布成功: {result.get('product')}")
        return 0

    print(f"[worker] 失败({stage}): {result.get('message', '未知错误')}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
