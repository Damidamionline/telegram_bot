import sqlite3
from datetime import datetime

DB_FILE = "bot_data.db"


def create_database():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # ───── Create users table ─────
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id      INTEGER PRIMARY KEY,
            name             TEXT,
            ref_by           INTEGER,
            slots            REAL DEFAULT 2,
            task_slots       REAL DEFAULT 0,
            ref_count_l1     INTEGER DEFAULT 0,
            twitter_handle   TEXT UNIQUE,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            banned_until     TIMESTAMP
        )
    """)

    # ───── Add any missing columns ─────
    c.execute("PRAGMA table_info(users)")
    existing_columns = {col[1] for col in c.fetchall()}

    if "post_ban_until" not in existing_columns:
        c.execute("ALTER TABLE users ADD COLUMN post_ban_until TIMESTAMP")
        print("✅ Added missing column to users: post_ban_until")

    if "last_post_at" not in existing_columns:
        c.execute("ALTER TABLE users ADD COLUMN last_post_at TIMESTAMP")
        print("✅ Added missing column to users: last_post_at")

    # ───── posts ───────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id   INTEGER REFERENCES users(telegram_id),
            post_link     TEXT,
            status        TEXT DEFAULT 'pending',
            submitted_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at   TIMESTAMP,
            expires_at    TIMESTAMP,
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
        )
    """)

    # ───── slot_logs ────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS slot_logs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id  INTEGER REFERENCES users(telegram_id),
            slots        REAL,
            reason       TEXT,
            note         TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
        )
    """)

    # ───── completions ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS completions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id  INTEGER REFERENCES users(telegram_id),
            post_id      INTEGER REFERENCES posts(id),
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(telegram_id, post_id),
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id),
            FOREIGN KEY (post_id) REFERENCES posts(id)
        )
    """)

# ───── verifications ────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS verifications (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id      INTEGER,
            doer_id      INTEGER,
            owner_id     INTEGER,
            status       TEXT DEFAULT 'pending', -- 'confirmed', 'rejected'
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at   TIMESTAMP,
            confirmed    INTEGER DEFAULT 0,
            responded    INTEGER DEFAULT 0
        )
    """)

    # ───── Indexes ─────────────────────────────────────────────
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_posts_telegram_id ON posts(telegram_id)")

    conn.commit()
    conn.close()
    print("✅ Database schema is ready and up-to-date.")


if __name__ == "__main__":
    create_database()
