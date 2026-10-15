"""One-shot auto-generate worker.

Generates exactly one piece of content (image + caption + hashtags)
and saves it to the draft box, then exits. Posting is manual, so the
draft box is the hand-off point. Runs as its own process so a long
image/LLM call never blocks Streamlit or Tkinter.

Usage:
    python worker.py            # generate one draft now
    python worker.py --dry-run  # generate without saving (test run)
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
LOCK_FILE = DATA_DIR / "generate.lock"
LOCK_MAX_AGE_S = 600


def _lock_reason() -> str | None:
    """None when free to run, otherwise the reason it is locked."""
    try:
        if LOCK_FILE.exists():
            age = time.time() - LOCK_FILE.stat().st_mtime
            if age < LOCK_MAX_AGE_S:
                holder = LOCK_FILE.read_text(encoding="utf-8", errors="replace").strip()
                return f"已有生成任务在进行中（{age:.0f} 秒前启动，{holder}）"
    except Exception:
        pass
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="InsAuto one-shot generate worker")
    parser.add_argument("--dry-run", action="store_true",
                        help="generate without saving to the draft box (test run)")
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
        from ins账号自动化.automation import run_auto_generate
        result = run_auto_generate(dry_run=args.dry_run)
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
            print(f"[worker] 测试完成: {result.get('product')} -> {result.get('image')}（未保存）")
        else:
            print(f"[worker] 生成完成: {result.get('product')} -> 已存入草稿箱（去网页面板复制文案）")
        return 0

    print(f"[worker] 失败({stage}): {result.get('message', '未知错误')}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
