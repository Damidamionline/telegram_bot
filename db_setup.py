import sqlite3
from datetime import datetime

DB_FILE = "bot_data.db"


def create_database():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # ───── users ───────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id           INTEGER PRIMARY KEY,
            name                  TEXT,
            ref_by                INTEGER,
            slots                 REAL DEFAULT 2,
            task_slots            REAL DEFAULT 0,
            ref_count_l1          INTEGER DEFAULT 0,
            twitter_handle        TEXT,
            twitter_id            TEXT,
            twitter_access_token  TEXT,
            twitter_refresh_token TEXT,
            token_expires_at      TIMESTAMP,
            created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Auto-add any missing columns
    c.execute("PRAGMA table_info(users)")
    existing_columns = {col[1] for col in c.fetchall()}

    additional_columns = [
        ("twitter_id", "TEXT"),
        ("twitter_refresh_token", "TEXT"),
        ("token_expires_at", "TIMESTAMP"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("last_updated", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]

    for column, col_type in additional_columns:
        if column not in existing_columns:
            c.execute(f"ALTER TABLE users ADD COLUMN {column} {col_type}")
            print(f"✅ Added missing column to users: {column}")

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

    # ───── slot_log ────────────────────────────────────────────
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

    # ───── Indexes ─────────────────────────────────────────────
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_posts_telegram_id ON posts(telegram_id)")

    conn.commit()
    conn.close()
    print("✅ Database schema is ready and up-to-date.")


def migrate_existing_data():
    """Backfill any existing rows with NULLs in new columns"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        # Twitter ID fallback
        c.execute("""
            UPDATE users
            SET twitter_id = COALESCE(twitter_id, ''),
                twitter_refresh_token = COALESCE(twitter_refresh_token, ''),
                token_expires_at = COALESCE(token_expires_at, NULL),
                created_at = COALESCE(created_at, datetime('now')),
                last_updated = datetime('now')
        """)
        conn.commit()
        print("✅ Migrated existing user data where needed.")
    except sqlite3.Error as e:
        print(f"⚠️ Migration skipped or failed: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    create_database()
    migrate_existing_data()
