"""Standalone automation worker — runs in separate process (no asyncio conflict)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ins账号自动化.automation import automation_worker
from ins账号自动化.db import state_get, init_db
from ins账号自动化.config import IG_USERNAME

if __name__ == "__main__":
    init_db()
    print("[worker] Started (PID={})".format(__import__("os").getpid()))

    def stop_check():
        """Read running flag from DB — Streamlit sets this."""
        s = state_get()
        return not s.get("running", False)

    automation_worker(IG_USERNAME, sessionid="", stop_check=stop_check)
    print("[worker] Stopped")
