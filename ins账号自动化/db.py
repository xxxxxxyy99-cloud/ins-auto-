"""SQLite persistence layer — replaces JSON file storage."""

import sqlite3
import json
import threading
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "app.db"

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


@contextmanager
def tx():
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    with tx() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT NOT NULL,
                caption TEXT NOT NULL,
                product TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT NOT NULL,
                caption TEXT NOT NULL,
                product TEXT NOT NULL,
                posted_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                product TEXT,
                message TEXT,
                metadata TEXT,
                severity TEXT NOT NULL DEFAULT 'info',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                next_post TEXT,
                next_interval INTEGER DEFAULT 2,
                last_post TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                posts INTEGER DEFAULT 0,
                generated INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                queue_added INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS automation_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                state TEXT NOT NULL DEFAULT 'idle',
                running INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                current_step TEXT,
                error_count INTEGER DEFAULT 0,
                last_error TEXT,
                updated_at TEXT NOT NULL
            );
        """)


# ─── Queue ──────────────────────────────────────────────────

def queue_get_all() -> list[dict]:
    with tx() as conn:
        rows = conn.execute("SELECT * FROM queue WHERE status='pending' ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]


def queue_push(image_path: str, caption: str, product: str):
    now = datetime.now().isoformat()
    with tx() as conn:
        conn.execute(
            "INSERT INTO queue (image_path, caption, product, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (image_path, caption, product, "pending", now, now),
        )


def queue_pop() -> dict | None:
    with tx() as conn:
        row = conn.execute("SELECT * FROM queue WHERE status='pending' ORDER BY id ASC LIMIT 1").fetchone()
        if row is None:
            return None
        d = dict(row)
        conn.execute("UPDATE queue SET status='processing', updated_at=? WHERE id=?", (datetime.now().isoformat(), d["id"]))
        return d


def queue_mark_posted(item_id: int):
    with tx() as conn:
        conn.execute("UPDATE queue SET status='posted', updated_at=? WHERE id=?", (datetime.now().isoformat(), item_id))


def queue_mark_pending(item_id: int):
    with tx() as conn:
        conn.execute("UPDATE queue SET status='pending', updated_at=? WHERE id=?", (datetime.now().isoformat(), item_id))


def queue_remove(index: int):
    with tx() as conn:
        row = conn.execute("SELECT id FROM queue WHERE status='pending' ORDER BY id ASC LIMIT 1 OFFSET ?", (index,)).fetchone()
        if row:
            conn.execute("DELETE FROM queue WHERE id=?", (row["id"],))


def queue_update_caption(index: int, new_caption: str):
    with tx() as conn:
        row = conn.execute("SELECT id FROM queue WHERE status='pending' ORDER BY id ASC LIMIT 1 OFFSET ?", (index,)).fetchone()
        if row:
            conn.execute("UPDATE queue SET caption=?, updated_at=? WHERE id=?",
                         (new_caption, datetime.now().isoformat(), row["id"]))


def queue_count() -> int:
    with tx() as conn:
        return conn.execute("SELECT COUNT(*) FROM queue WHERE status='pending'").fetchone()[0]


def queue_clear():
    with tx() as conn:
        conn.execute("DELETE FROM queue WHERE status='pending'")


# ─── History ────────────────────────────────────────────────

def history_get_all() -> list[dict]:
    with tx() as conn:
        rows = conn.execute("SELECT * FROM history ORDER BY posted_at DESC").fetchall()
        return [dict(r) for r in rows]


def history_add(image_path: str, caption: str, product: str):
    now = datetime.now().isoformat()
    with tx() as conn:
        conn.execute(
            "INSERT INTO history (image_path, caption, product, posted_at) VALUES (?,?,?,?)",
            (image_path, caption, product, now),
        )


def history_count() -> int:
    with tx() as conn:
        return conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]


def history_clear():
    with tx() as conn:
        conn.execute("DELETE FROM history")


# ─── Activity Log ───────────────────────────────────────────

def log_event(event: str, product: str | None = None, message: str | None = None,
              metadata: dict | None = None, severity: str = "info"):
    now = datetime.now().isoformat()
    meta_str = json.dumps(metadata, ensure_ascii=False) if metadata else None
    with tx() as conn:
        conn.execute(
            "INSERT INTO activity_log (event, product, message, metadata, severity, created_at) VALUES (?,?,?,?,?,?)",
            (event, product, message, meta_str, severity, now),
        )


def log_get_recent(limit: int = 20) -> list[dict]:
    with tx() as conn:
        rows = conn.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


# ─── Schedule ───────────────────────────────────────────────

def schedule_get() -> dict:
    with tx() as conn:
        row = conn.execute("SELECT * FROM schedule ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else {}


def schedule_save(data: dict):
    now = datetime.now().isoformat()
    with tx() as conn:
        existing = conn.execute("SELECT id FROM schedule ORDER BY id DESC LIMIT 1").fetchone()
        if existing:
            conn.execute(
                "UPDATE schedule SET next_post=?, next_interval=?, last_post=?, updated_at=? WHERE id=?",
                (data.get("next_post"), data.get("next_interval"), data.get("last_post"), now, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO schedule (next_post, next_interval, last_post, updated_at) VALUES (?,?,?,?)",
                (data.get("next_post"), data.get("next_interval"), data.get("last_post"), now),
            )


# ─── Settings ───────────────────────────────────────────────

DEFAULT_SETTINGS = {
    "interval_days": "2",
    "niche": "kitchen gadgets & home bar",
    "style": "casual",
    "audience": "home cooks, juice lovers & cocktail enthusiasts",
    "llm_model": "qwen/qwen-2.5-7b-instruct",
    "image_model": "pollinations",
    "hashtags": "#厨房好物 #厨房神器 #家居好物 #懒人厨房 #榨汁 #饮品diy #夏日饮品 #冰饮 #homemade #kitchengadgets #juicebar #summerdrinks",
    "caption_instructions": "",
}


def settings_get() -> dict:
    with tx() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        result = dict(DEFAULT_SETTINGS)
        for r in rows:
            result[r["key"]] = r["value"]
        return result


def settings_set(**kwargs):
    with tx() as conn:
        for k, v in kwargs.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, str(v)),
            )


# ─── Automation State ───────────────────────────────────────

def state_get() -> dict:
    with tx() as conn:
        row = conn.execute("SELECT * FROM automation_state ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            return dict(row)
        return {"state": "idle", "running": False, "started_at": None, "current_step": None,
                "error_count": 0, "last_error": None}


def state_set(**kwargs):
    now = datetime.now().isoformat()
    with tx() as conn:
        existing = conn.execute("SELECT id FROM automation_state ORDER BY id DESC LIMIT 1").fetchone()
        if existing:
            cols = ", ".join(f"{k}=?" for k in kwargs)
            vals = list(kwargs.values()) + [now, existing["id"]]
            conn.execute(f"UPDATE automation_state SET {cols}, updated_at=? WHERE id=?", vals)
        else:
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join(["?"] * len(kwargs))
            vals = list(kwargs.values())
            conn.execute(f"INSERT INTO automation_state ({cols}, updated_at) VALUES ({placeholders}, ?)", vals + [now])


# ─── Analytics ──────────────────────────────────────────────

def analytics_today() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    with tx() as conn:
        row = conn.execute("SELECT * FROM analytics WHERE date=?", (today,)).fetchone()
        if row:
            return dict(row)
        return {"date": today, "posts": 0, "generated": 0, "errors": 0, "queue_added": 0}


def analytics_increment(field: str):
    today = datetime.now().strftime("%Y-%m-%d")
    with tx() as conn:
        existing = conn.execute("SELECT id FROM analytics WHERE date=?", (today,)).fetchone()
        if existing:
            conn.execute(f"UPDATE analytics SET {field}={field}+1 WHERE date=?", (today,))
        else:
            conn.execute(
                f"INSERT INTO analytics (date, {field}) VALUES (?, 1)", (today,)
            )


def analytics_overview(days: int = 14) -> list[dict]:
    with tx() as conn:
        rows = conn.execute(
            "SELECT * FROM analytics ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()
        return [dict(r) for r in rows]


def analytics_totals() -> dict:
    with tx() as conn:
        r = conn.execute("SELECT COALESCE(SUM(posts),0) as posts, COALESCE(SUM(generated),0) as generated, COALESCE(SUM(errors),0) as errors FROM analytics").fetchone()
        return dict(r)


# ─── Migration from JSON ────────────────────────────────────

def migrate_from_json():
    """One-time migration: copy existing JSON data into SQLite."""
    import json as j
    JSON_DIR = DATA_DIR  # same directory

    def _read(fname):
        p = JSON_DIR / fname
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return j.load(f)
        return None

    queue_data = _read("post_queue.json")
    if queue_data and isinstance(queue_data, list):
        for item in queue_data:
            try:
                queue_push(item["image_path"], item["caption"], item["product"])
            except:
                pass

    hist_data = _read("posted_history.json")
    if hist_data and isinstance(hist_data, list):
        now = datetime.now().isoformat()
        for item in hist_data:
            try:
                history_add(item["image_path"], item["caption"], item["product"])
            except:
                pass

    sched_data = _read("next_post.json")
    if sched_data and isinstance(sched_data, dict):
        schedule_save(sched_data)

    sett_data = _read("automation_settings.json")
    if sett_data and isinstance(sett_data, dict):
        settings_set(**sett_data)

    log_event("system", message="数据已从 JSON 迁移到 SQLite")


# ─── Compound helpers (moved from storage.py) ────────────────

def get_status() -> dict:
    s = state_get()
    total_gen = sum(r["generated"] for r in analytics_overview(999))
    total_post = sum(r["posts"] for r in analytics_overview(999))
    return {
        "running": bool(s.get("running", False)),
        "started_at": s.get("started_at"),
        "total_generated": total_gen,
        "total_posted": total_post,
        "last_posted": None,
        "state": s.get("state", "idle"),
        "error_count": s.get("error_count", 0),
        "last_error": s.get("last_error"),
    }


def set_running(running: bool):
    current = state_get()
    started = current.get("started_at")
    if running and not started:
        started = datetime.now().isoformat()
    state_set(running=running, started_at=started)


def increment_generated(n: int = 1):
    for _ in range(n):
        analytics_increment("generated")


def increment_posted():
    analytics_increment("posts")


# ─── Public aliases ──────────────────────────────────────────

get_queue = queue_get_all
queue_post = queue_push
pop_queue = queue_pop
add_to_history = history_add
get_history = history_get_all
clear_history = history_clear
get_settings = settings_get
save_settings = settings_set
get_recent_activity = log_get_recent
get_schedule = schedule_get
save_schedule = schedule_save


# ─── Init ───────────────────────────────────────────────────

init_db()
