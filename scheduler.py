"""Schedule watcher for automatic Instagram posting.

Loops with a short check interval; when the schedule is due it spawns
worker.py as a child process (Playwright isolation), waits for it,
records the result, and computes the next run time. Runs standalone
(启动定时发布.bat) or is supervised by launcher.py.

Usage:
    python scheduler.py                # watch forever
    python scheduler.py --once         # check once, run if due, exit
    python scheduler.py --dry-run      # pass --dry-run to workers (no posting)
    python scheduler.py --interval 15  # check every N seconds (default 30)
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DATA_DIR = ROOT / "ins账号自动化" / "data"
HEARTBEAT = DATA_DIR / "scheduler.lock"
HEARTBEAT_FRESH_S = 90


def _say(msg: str):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def _heartbeat():
    try:
        DATA_DIR.mkdir(exist_ok=True)
        HEARTBEAT.write_text(f"pid={os.getpid()}", encoding="utf-8")
    except Exception:
        pass


def _check_and_run(dry_run: bool, once: bool) -> int:
    from ins账号自动化.automation import compute_next_run
    from ins账号自动化.db import get_settings, settings_set

    settings = get_settings()
    nxt = compute_next_run(settings)
    if nxt is None:
        settings_set(schedule_next_run="")
        if once:
            _say("定时发布未启用（schedule_enabled=0），无事可做")
        return 0

    now = datetime.now()
    if now < nxt:
        settings_set(schedule_next_run=nxt.isoformat(timespec="minutes"))
        if once:
            _say(f"未到发布时间，下次: {nxt:%m-%d %H:%M}")
        return 0

    _say(f"计划时间 {nxt:%m-%d %H:%M} 已到，启动 worker{'（演示模式）' if dry_run else ''}...")
    cmd = [sys.executable, "-u", str(ROOT / "worker.py")]
    if dry_run:
        cmd.append("--dry-run")
    rc = subprocess.run(cmd, cwd=str(ROOT)).returncode

    if dry_run:
        _say("演示运行结束（不推进计划时间）")
        return 0 if rc == 0 else 1

    finished = datetime.now()
    settings_set(
        schedule_last_run=finished.isoformat(timespec="minutes"),
        schedule_last_result=("✅ 成功 " if rc == 0 else "❌ 失败 ") + finished.strftime("%m-%d %H:%M"),
    )
    nxt2 = compute_next_run(get_settings())
    if nxt2:
        settings_set(schedule_next_run=nxt2.isoformat(timespec="minutes"))
        _say(f"本次完成（rc={rc}），下次发布: {nxt2:%m-%d %H:%M}")
    return 0 if rc == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="InsAuto schedule watcher")
    parser.add_argument("--once", action="store_true", help="check once and exit")
    parser.add_argument("--dry-run", action="store_true", help="workers run without posting")
    parser.add_argument("--interval", type=int, default=30, help="check interval in seconds")
    args = parser.parse_args()

    if HEARTBEAT.exists():
        try:
            age = time.time() - HEARTBEAT.stat().st_mtime
            if age < HEARTBEAT_FRESH_S:
                _say(f"已有定时服务在运行（{age:.0f} 秒前心跳），本进程退出")
                return 4
        except Exception:
            pass

    _say("定时服务启动" + ("（单次检查）" if args.once else f"，检查间隔 {max(5, args.interval)} 秒"))
    try:
        while True:
            _heartbeat()
            try:
                _check_and_run(args.dry_run, args.once)
            except Exception as e:
                _say(f"检查出错: {e}")
            if args.once:
                return 0
            time.sleep(max(5, args.interval))
    except KeyboardInterrupt:
        _say("定时服务已停止")
        return 0
    finally:
        try:
            HEARTBEAT.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
