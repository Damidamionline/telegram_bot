from datetime import datetime, timedelta
import sqlite3

DB_FILE = "bot_data.db"

# ───── Twitter handle helpers ────────────────────────────


def set_twitter_handle(telegram_id: int, handle: str) -> bool:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Check if handle is already taken by another user
    c.execute(
        "SELECT telegram_id FROM users WHERE twitter_handle = ? AND telegram_id != ?",
        (handle, telegram_id)
    )
    if c.fetchone():
        conn.close()
        return False  # Handle is already in use

    # Set the handle
    c.execute(
        "UPDATE users SET twitter_handle = ? WHERE telegram_id = ?",
        (handle, telegram_id)
    )
    conn.commit()
    conn.close()
    return True


def get_twitter_handle(telegram_id: int) -> str | None:
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute(
        "SELECT twitter_handle FROM users WHERE telegram_id = ?",
        (telegram_id,)
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] else None

# ───── USERS ─────────────────────────────────────────────


def add_user(telegram_id, name, ref_by=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Already registered?
    if c.execute("SELECT 1 FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone():
        conn.close()
        return False

    # Insert new user (default 2 slots)
    c.execute(
        "INSERT INTO users (telegram_id, name, slots, task_slots, ref_count_l1) VALUES (?, ?, 2, 0, 0)",
        (telegram_id, name)
    )

    # Credit referrer (Level-1 only) + log
    if ref_by:
        c.execute("""
            UPDATE users
            SET slots = slots + 0.5,
                ref_count_l1 = ref_count_l1 + 1
            WHERE telegram_id = ?
        """, (ref_by,))

        # Log slot gain
        c.execute("""
            INSERT INTO slot_logs (telegram_id, slots, reason, created_at)
            VALUES (?, ?, 'referral', ?)
        """, (ref_by, 0.5, datetime.utcnow()))

    conn.commit()
    conn.close()
    return True


def get_user(telegram_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    user = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_slots(telegram_id: int) -> int:
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute(
        "SELECT slots FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return row[0] if row else 0


def deduct_slot_by_admin(telegram_id: int) -> bool:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if c.execute("SELECT slots FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()[0] > 0:
        c.execute(
            "UPDATE users SET slots = slots - 1 WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


def add_task_slot(telegram_id: int, amount: float):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "UPDATE users SET task_slots = task_slots + ?, slots = slots + ? WHERE telegram_id = ?",
        (amount, amount, telegram_id)
    )
    c.execute(
        "INSERT INTO slot_logs (telegram_id, slots, reason, created_at) VALUES (?, ?, 'task', ?)",
        (telegram_id, amount, datetime.utcnow())
    )
    conn.commit()
    conn.close()


def has_completed_post(telegram_id: int, post_id: int) -> bool:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM completions WHERE telegram_id = ? AND post_id = ?", (telegram_id, post_id))
    result = c.fetchone()
    conn.close()
    return result is not None


def mark_post_completed(telegram_id: int, post_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO completions (telegram_id, post_id, created_at) VALUES (?, ?, ?)",
        (telegram_id, post_id, datetime.utcnow())
    )
    conn.commit()
    conn.close()

# ───── POSTS ─────────────────────────────────────────────


def save_post(telegram_id: int, post_link: str):
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT INTO posts (telegram_id, post_link) VALUES (?, ?)",
        (telegram_id, post_link),
    )
    conn.commit()
    conn.close()


def get_post_link_by_id(post_id):
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute(
        "SELECT post_link FROM posts WHERE id = ?", (post_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def get_pending_posts(limit: int = 5):
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute(
        """
        SELECT p.id, p.post_link, u.name, p.telegram_id
        FROM posts p
        JOIN users u ON u.telegram_id = p.telegram_id
        WHERE p.status = 'pending'
        ORDER BY p.submitted_at ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def set_post_status(post_id: int, status: str):
    conn = sqlite3.connect(DB_FILE)
    if status == "approved":
        conn.execute(
            "UPDATE posts SET status = ?, approved_at = ? WHERE id = ?",
            (status, datetime.utcnow(), post_id)
        )
    else:
        conn.execute("UPDATE posts SET status = ? WHERE id = ?",
                     (status, post_id))
    conn.commit()
    conn.close()


def get_recent_approved_posts(hours: int = 24):
    since = datetime.utcnow() - timedelta(hours=hours)
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute(
        """
        SELECT p.id, p.post_link, u.name
        FROM posts p
        JOIN users u ON p.telegram_id = u.telegram_id
        WHERE p.status = 'approved' AND p.approved_at >= ?
        ORDER BY p.submitted_at DESC
        """,
        (since,),
    ).fetchall()
    conn.close()
    return rows

# ───── PROFILE STATS ─────────────────────────────────────


def get_user_stats(telegram_id: int):
    conn = sqlite3.connect(DB_FILE)
    approved, rejected, task_slots, ref_slots = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM posts WHERE telegram_id = ? AND status = 'approved'),
            (SELECT COUNT(*) FROM posts WHERE telegram_id = ? AND status = 'rejected'),
            (SELECT IFNULL(SUM(slots), 0) FROM slot_logs WHERE telegram_id = ? AND reason = 'task'),
            (SELECT IFNULL(SUM(slots), 0) FROM slot_logs WHERE telegram_id = ? AND reason = 'referral')
        """,
        (telegram_id, telegram_id, telegram_id, telegram_id),
    ).fetchone()
    conn.close()
    return approved, rejected, task_slots, ref_slots

# ───── EXPIRATION ────────────────────────────────────────


def expire_old_posts():
    cutoff = datetime.utcnow() - timedelta(hours=24)
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        """
        UPDATE posts
        SET status = 'expired'
        WHERE status = 'approved' AND approved_at IS NOT NULL AND approved_at <= ?
        """,
        (cutoff,),
    )
    conn.commit()
    conn.close()
    print("🕒 Expired old approved posts.")

# ───── ADMIN ALERTS ──────────────────────────────────────


def get_pending_count():
    conn = sqlite3.connect(DB_FILE)
    count = conn.execute(
        "SELECT COUNT(*) FROM posts WHERE status = 'pending'").fetchone()[0]
    conn.close()
    return count
