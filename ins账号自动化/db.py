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
        _local.conn.execute("PRAGMA busy_timeout=5000")
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
        # Migration: add topic column if missing (pre-v2.1 DBs)
        try:
            conn.execute("ALTER TABLE drafts ADD COLUMN topic TEXT")
        except Exception:
            pass  # column already exists

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT NOT NULL UNIQUE,
                product TEXT,
                category TEXT,
                prompt TEXT,
                model TEXT,
                is_favorite INTEGER DEFAULT 0,
                tags TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT NOT NULL,
                caption TEXT NOT NULL,
                hashtags TEXT,
                product TEXT,
                category TEXT,
                topic TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
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
        """)


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


# ─── Settings ───────────────────────────────────────────────

DEFAULT_SETTINGS = {
    "interval_days": "2",
    "publish_hashtag_limit": "15",
    "niche": "kitchen gadgets & home bar",
    "style": "casual",
    "audience": "home cooks, juice lovers & cocktail enthusiasts",
    "llm_model": "qwen/qwen-2.5-7b-instruct",
    "image_model": "gemini",
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


# ─── Analytics ──────────────────────────────────────────────


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


# ─── Assets (image library) ─────────────────────────────────

def asset_add(image_path: str, product: str = "", category: str = "",
              prompt: str = "", model: str = "", tags: str = ""):
    now = datetime.now().isoformat()
    with tx() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO assets (image_path, product, category, prompt, model, tags, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (image_path, product, category, prompt, model, tags, now),
        )


def asset_get_all(category: str = "", favorite_only: bool = False,
                  search: str = "", limit: int = 100) -> list[dict]:
    with tx() as conn:
        wheres = []
        params = []
        if category:
            wheres.append("category=?")
            params.append(category)
        if favorite_only:
            wheres.append("is_favorite=1")
        if search:
            wheres.append("(product LIKE ? OR tags LIKE ? OR prompt LIKE ?)")
            params.extend([f"%{search}%"] * 3)
        sql = "SELECT * FROM assets"
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def asset_toggle_favorite(image_path: str) -> bool:
    with tx() as conn:
        row = conn.execute("SELECT id, is_favorite FROM assets WHERE image_path=?", (image_path,)).fetchone()
        if row:
            new_val = 0 if row["is_favorite"] else 1
            conn.execute("UPDATE assets SET is_favorite=? WHERE id=?", (new_val, row["id"]))
            return bool(new_val)
        return False


def asset_delete(image_path: str):
    with tx() as conn:
        conn.execute("DELETE FROM assets WHERE image_path=?", (image_path,))


def asset_count() -> int:
    with tx() as conn:
        return conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]


def asset_get_by_category() -> list[dict]:
    with tx() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM assets WHERE category != '' GROUP BY category ORDER BY cnt DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ─── Drafts ──────────────────────────────────────────────────

def draft_save(image_path: str, caption: str, hashtags: str = "",
               product: str = "", category: str = "", topic: str = "") -> int:
    now = datetime.now().isoformat()
    with tx() as conn:
        cur = conn.execute(
            "INSERT INTO drafts (image_path, caption, hashtags, product, category, topic, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (image_path, caption, hashtags, product, category, topic, "draft", now, now),
        )
        return cur.lastrowid


def draft_get_all(status: str = "") -> list[dict]:
    with tx() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM drafts WHERE status=? ORDER BY updated_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM drafts ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


def draft_get(draft_id: int) -> dict | None:
    with tx() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
        return dict(row) if row else None


def draft_update(draft_id: int, **kwargs):
    now = datetime.now().isoformat()
    kwargs["updated_at"] = now
    with tx() as conn:
        cols = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [draft_id]
        conn.execute(f"UPDATE drafts SET {cols} WHERE id=?", vals)


def draft_delete(draft_id: int):
    with tx() as conn:
        conn.execute("DELETE FROM drafts WHERE id=?", (draft_id,))


def draft_submit_review(draft_id: int):
    """Submit a draft to the review center."""
    now = datetime.now().isoformat()
    with tx() as conn:
        conn.execute(
            "UPDATE drafts SET status='review', updated_at=? WHERE id=?",
            (now, draft_id),
        )


def draft_approve(draft_id: int):
    """Approve a reviewed item — move back to draft (ready to publish)."""
    now = datetime.now().isoformat()
    with tx() as conn:
        conn.execute(
            "UPDATE drafts SET status='draft', updated_at=? WHERE id=?",
            (now, draft_id),
        )


def draft_reject(draft_id: int):
    """Reject a reviewed item — delete it from drafts."""
    with tx() as conn:
        conn.execute("DELETE FROM drafts WHERE id=?", (draft_id,))


def draft_search(query: str = "", topic: str = "", tag: str = "",
                 status: str = "", limit: int = 100) -> list[dict]:
    """Unified search across drafts by keyword, topic, tag, and status.

    Args:
        query: Search keyword (matches caption, product, hashtags)
        topic: Filter by content topic (travel, fashion, etc.)
        tag: Filter by specific hashtag (without # prefix)
        status: Filter by status (draft, review, posted, or '' for all)
        limit: Max results
    """
    with tx() as conn:
        wheres = []
        params = []

        if query:
            wheres.append("(caption LIKE ? OR product LIKE ? OR hashtags LIKE ?)")
            params.extend([f"%{query}%"] * 3)

        if topic:
            wheres.append("topic=?")
            params.append(topic)

        if tag:
            # Tag filtering: search in hashtags column
            wheres.append("hashtags LIKE ?")
            params.append(f"%{tag}%")

        if status:
            wheres.append("status=?")
            params.append(status)

        sql = "SELECT * FROM drafts"
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def review_count() -> int:
    """Count items awaiting review."""
    with tx() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE status='review'"
        ).fetchone()[0]


def draft_mark_posted(draft_id: int):
    now = datetime.now().isoformat()
    with tx() as conn:
        conn.execute(
            "UPDATE drafts SET status='posted', updated_at=? WHERE id=?",
            (now, draft_id),
        )


def draft_count(status: str = "") -> int:
    with tx() as conn:
        if status:
            return conn.execute("SELECT COUNT(*) FROM drafts WHERE status=?", (status,)).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]


# ─── Public aliases ──────────────────────────────────────────

add_to_history = history_add
get_history = history_get_all
clear_history = history_clear
get_settings = settings_get
save_settings = settings_set
get_recent_activity = log_get_recent


# ─── Init ───────────────────────────────────────────────────

init_db()
