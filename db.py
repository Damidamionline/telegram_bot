from datetime import datetime, timedelta
import sqlite3
import re

DB_FILE = "bot_data.db"

# ───── Twitter Handle Helpers ────────────────────────────


def set_twitter_handle(telegram_id: int, handle: str) -> bool:
    """Sets a user's Twitter handle if not taken by another user"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute(
        "SELECT 1 FROM users WHERE twitter_handle = ? AND telegram_id != ?",
        (handle, telegram_id)
    )
    if c.fetchone():
        conn.close()
        return False

    c.execute(
        "UPDATE users SET twitter_handle = ?, last_updated = ? WHERE telegram_id = ?",
        (handle, datetime.utcnow(), telegram_id)
    )
    conn.commit()
    conn.close()
    return True


def is_valid_tweet_link(link: str) -> bool:
    pattern = r"^https://(twitter\.com|x\.com)/[^/]+/status/\d+"
    return bool(re.match(pattern, link.strip()))


def is_user_banned(telegram_id: int) -> bool:
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute(
        "SELECT post_ban_until FROM users WHERE telegram_id = ?",
        (telegram_id,)
    ).fetchone()
    conn.close()

    if row and row[0]:
        ban_time = datetime.fromisoformat(row[0])
        return datetime.utcnow() < ban_time
    return False


def get_user_active_posts(telegram_id: int):
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("""
        SELECT id, post_link, approved_at
        FROM posts
        WHERE telegram_id = ? AND status = 'approved'
        AND approved_at >= datetime('now', '-24 hours')
    """, (telegram_id,)).fetchall()
    conn.close()
    return rows


def update_last_post_time(user_id: int):
    """Update the last post timestamp for a user"""
    # Implementation depends on your database
    # Example for SQLite:
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("UPDATE users SET last_post_at = ? WHERE telegram_id = ?",
              (datetime.utcnow().isoformat(), user_id))
    conn.commit()
    conn.close()


def is_in_cooldown(telegram_id: int, cooldown_hours: int) -> tuple[bool, str | None]:
    """Returns True if user is in cooldown and how much time is left, otherwise False."""
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute(
        "SELECT last_post_at FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()

    if row and row[0]:
        last_post_at = datetime.fromisoformat(row[0])
        time_since_last_post = datetime.utcnow() - last_post_at

        if time_since_last_post.total_seconds() < cooldown_hours * 3600:
            remaining = timedelta(hours=cooldown_hours) - time_since_last_post
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes = remainder // 60
            return True, f"{hours}h {minutes}m"
    return False, None


def get_cooldown_remaining(user_id: int, cooldown_hours: int) -> str:
    """Get formatted string of remaining cooldown time"""
    user_data = get_user(user_id)
    if not user_data or not user_data.get("last_post_at"):
        return "0 hours 0 minutes"

    last_post_at = datetime.fromisoformat(user_data["last_post_at"])
    time_since_last_post = datetime.utcnow() - last_post_at
    remaining = timedelta(hours=cooldown_hours) - time_since_last_post

    # Format as "X hours Y minutes"
    hours = remaining.seconds // 3600
    minutes = (remaining.seconds % 3600) // 60
    return f"{hours} hours {minutes} minutes"


def get_twitter_handle(telegram_id: int) -> str | None:
    """Gets the user's saved Twitter handle"""
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute(
        "SELECT twitter_handle FROM users WHERE telegram_id = ?",
        (telegram_id,)
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] else None

# ───── Users ─────────────────────────────────────────────


def add_user(telegram_id, name, ref_by=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    if c.execute("SELECT 1 FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone():
        conn.close()
        return False

    c.execute(
        "INSERT INTO users (telegram_id, name, ref_by, slots, task_slots, ref_count_l1) VALUES (?, ?, ?, 2, 0, 0)",
        (telegram_id, name, ref_by)
    )

    if ref_by:
        c.execute("""
            UPDATE users
            SET slots = slots + 0.5,
                ref_count_l1 = ref_count_l1 + 1
            WHERE telegram_id = ?
        """, (ref_by,))

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
        "SELECT slots FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def deduct_slot_by_admin(telegram_id: int) -> bool:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    row = c.execute("SELECT slots FROM users WHERE telegram_id = ?",
                    (telegram_id,)).fetchone()
    if row and row[0] > 0:
        c.execute(
            "UPDATE users SET slots = slots - 1 WHERE telegram_id = ?",
            (telegram_id,)
        )
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


def add_task_slot(telegram_id: int, amount: float):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        UPDATE users
        SET task_slots = task_slots + ?, slots = slots + ?, last_updated = ?
        WHERE telegram_id = ?
    """, (amount, amount, datetime.utcnow(), telegram_id))

    c.execute("""
        INSERT INTO slot_logs (telegram_id, slots, reason, created_at)
        VALUES (?, ?, 'task', ?)
    """, (telegram_id, amount, datetime.utcnow()))
    conn.commit()
    conn.close()

# ───── Raid Completion ──────────────────────────────────


def has_completed_post(telegram_id: int, post_id: int) -> bool:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM completions WHERE telegram_id = ? AND post_id = ?",
        (telegram_id, post_id)
    )
    result = c.fetchone()
    conn.close()
    return result is not None


def mark_post_completed(telegram_id: int, post_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO completions (telegram_id, post_id, created_at)
        VALUES (?, ?, ?)
    """, (telegram_id, post_id, datetime.utcnow()))
    conn.commit()
    conn.close()

# ───── Posts ─────────────────────────────────────────────


def save_post(telegram_id: int, post_link: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO posts (telegram_id, post_link) VALUES (?, ?)",
        (telegram_id, post_link)
    )
    c.execute(
        "UPDATE users SET last_post_at = ? WHERE telegram_id = ?",
        (datetime.utcnow(), telegram_id)
    )
    conn.commit()
    conn.close()


def get_post_link_by_id(post_id):
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute(
        "SELECT post_link FROM posts WHERE id = ?", (post_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def get_pending_posts(limit: int = 5):
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("""
        SELECT p.id, p.post_link, u.name, p.telegram_id
        FROM posts p
        JOIN users u ON u.telegram_id = p.telegram_id
        WHERE p.status = 'pending'
        ORDER BY p.submitted_at ASC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return rows


def set_post_status(post_id: int, status: str):
    conn = sqlite3.connect(DB_FILE)
    if status == "approved":
        conn.execute("""
            UPDATE posts
            SET status = ?, approved_at = ?
            WHERE id = ?
        """, (status, datetime.utcnow(), post_id))
    else:
        conn.execute(
            "UPDATE posts SET status = ? WHERE id = ?",
            (status, post_id)
        )
    conn.commit()
    conn.close()


def get_recent_approved_posts(hours: int = 24, with_time=False):
    since = datetime.utcnow() - timedelta(hours=hours)
    conn = sqlite3.connect(DB_FILE)
    if with_time:
        rows = conn.execute("""
            SELECT p.id, p.post_link, u.name, p.approved_at
            FROM posts p
            JOIN users u ON p.telegram_id = u.telegram_id
            WHERE p.status = 'approved' AND p.approved_at >= ?
            ORDER BY p.submitted_at DESC
        """, (since,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT p.id, p.post_link, u.name
            FROM posts p
            JOIN users u ON p.telegram_id = u.telegram_id
            WHERE p.status = 'approved' AND p.approved_at >= ?
            ORDER BY p.submitted_at DESC
        """, (since,)).fetchall()
    conn.close()
    return rows


def get_post_owner_id(post_id: int) -> int | None:
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute(
        "SELECT telegram_id FROM posts WHERE id = ?", (post_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def create_verification(post_id: int, doer_id: int, owner_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER,
            doer_id INTEGER,
            owner_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            confirmed INTEGER DEFAULT 0,
            responded INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        INSERT INTO verifications (post_id, doer_id, owner_id)
        VALUES (?, ?, ?)
    """, (post_id, doer_id, owner_id))
    conn.commit()
    conn.close()


def close_verification(post_id: int, doer_id: int):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        UPDATE verifications
        SET status = 'confirmed', updated_at = CURRENT_TIMESTAMP
        WHERE post_id = ? AND doer_id = ?
    """, (post_id, doer_id))
    conn.commit()
    conn.close()


def auto_approve_stale_posts(context=None):
    """Automatically approve posts still pending after 1 hour and notify users."""
    cutoff = datetime.utcnow() - timedelta(hours=1)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Fetch posts to approve
    posts = c.execute("""
        SELECT id, telegram_id, post_link
        FROM posts
        WHERE status = 'pending' AND submitted_at <= ?
    """, (cutoff,)).fetchall()

    # Approve them
    c.execute("""
        UPDATE posts
        SET status = 'approved', approved_at = ?
        WHERE status = 'pending' AND submitted_at <= ?
    """, (datetime.utcnow(), cutoff))

    conn.commit()
    conn.close()

    if posts and context:
        for post in posts:
            try:
                context.bot.send_message(
                    chat_id=post["telegram_id"],
                    text=f"✅ Your post has been automatically approved:\n🔗 {post['post_link']}"
                )
            except Exception as e:
                print(f"❌ Failed to notify user {post['telegram_id']}: {e}")

    if posts:
        print(f"✅ Auto-approved {len(posts)} stale pending post(s).")


def ban_unresponsive_post_owners():
    """Ban users whose approved posts expired 4+ hours ago without confirming/rejecting raids."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Find expired posts older than 4 hours where no confirmation has been made
    cutoff = datetime.utcnow() - timedelta(hours=4)
    rows = c.execute("""
        SELECT p.telegram_id, p.id
        FROM posts p
        WHERE p.status = 'expired'
        AND p.expires_at <= ?
        AND EXISTS (
            SELECT 1 FROM verifications v
            WHERE v.post_id = p.id
            AND v.status = 'pending'
        )
    """, (cutoff,)).fetchall()

    for user_id, post_id in rows:
        # Ban user for 48 hours
        banned_until = datetime.utcnow() + timedelta(hours=48)
        c.execute("""
            UPDATE users
            SET banned_until = ?
            WHERE telegram_id = ?
        """, (banned_until.isoformat(), user_id))
        print(
            f"🚫 Banned user {user_id} for 48h due to inactivity on post {post_id}")

    conn.commit()
    conn.close()

# ───── Profile Stats ─────────────────────────────────────


def get_user_stats(telegram_id: int):
    conn = sqlite3.connect(DB_FILE)
    approved, rejected, task_slots, ref_slots = conn.execute("""
        SELECT
            (SELECT COUNT(*) FROM posts WHERE telegram_id = ? AND status = 'approved'),
            (SELECT COUNT(*) FROM posts WHERE telegram_id = ? AND status = 'rejected'),
            (SELECT IFNULL(SUM(slots), 0) FROM slot_logs WHERE telegram_id = ? AND reason = 'task'),
            (SELECT IFNULL(SUM(slots), 0) FROM slot_logs WHERE telegram_id = ? AND reason = 'referral')
    """, (telegram_id, telegram_id, telegram_id, telegram_id)).fetchone()
    conn.close()
    return approved, rejected, task_slots, ref_slots

# ───── Expiration ────────────────────────────────────────


def expire_old_posts():
    cutoff = datetime.utcnow() - timedelta(hours=24)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        UPDATE posts
        SET status = 'expired'
        WHERE status = 'approved' AND approved_at IS NOT NULL AND approved_at <= ?
    """, (cutoff,))
    conn.commit()
    conn.close()
    print("🕒 Expired old approved posts.")


def update_verification_status(post_id: int, doer_id: int, status: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        UPDATE verifications
        SET confirmed = ?, responded = 1, updated_at = CURRENT_TIMESTAMP
        WHERE post_id = ? AND doer_id = ?
    """, (1 if status == "confirmed" else 0, post_id, doer_id))
    conn.commit()
    conn.close()


def get_expired_unconfirmed_verifications():
    cutoff = datetime.utcnow() - timedelta(hours=28)
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("""
        SELECT DISTINCT v.owner_id
        FROM verifications v
        JOIN posts p ON v.post_id = p.id
        WHERE v.status = 'pending'
        AND p.status = 'expired'
        AND p.approved_at <= ?
    """, (cutoff,)).fetchall()
    conn.close()
    return [row[0] for row in rows]


def ban_user_from_posting(telegram_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        UPDATE users
        SET post_ban_until = datetime('now', '+48 hours')
        WHERE telegram_id = ?
    """, (telegram_id,))
    conn.commit()
    conn.close()


def get_verifications_for_post(post_id: int):
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("""
        SELECT v.doer_id, u.name, u.twitter_handle, v.status
        FROM verifications v
        JOIN users u ON u.telegram_id = v.doer_id
        WHERE v.post_id = ?
    """, (post_id,)).fetchall()
    conn.close()
    return rows


# ───── Admin Dashboard ───────────────────────────────────


def get_pending_count():
    conn = sqlite3.connect(DB_FILE)
    count = conn.execute(
        "SELECT COUNT(*) FROM posts WHERE status = 'pending'"
    ).fetchone()[0]
    conn.close()
    return count
