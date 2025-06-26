# db_setup.py
import sqlite3

DB_FILE = "bot_data.db"


def create_database():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # ───── users ─────────────────────────────────────────
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id      INTEGER PRIMARY KEY,
            name             TEXT,
            ref_by           INTEGER,
            slots            REAL    DEFAULT 2,
            task_slots       REAL    DEFAULT 0,
            ref_count_l1     INTEGER DEFAULT 0,
            twitter_handle   TEXT
            twitter_access_token   TEXT,
            twitter_refresh_token  TEXT,
            token_expires_at       TIMESTAMP

        )
        """
    )

    # ───── posts ─────────────────────────────────────────
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id   INTEGER,
            post_link     TEXT,
            status        TEXT DEFAULT 'pending',
            submitted_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at   TIMESTAMP
        )
        """
    )

    # ───── slot_log ──────────────────────────────────────
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS slot_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id  INTEGER,
            slots        REAL,
            reason       TEXT,
            note         TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # ───── completions ───────────────────────────────────
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS completions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id  INTEGER,
            post_id      INTEGER,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(telegram_id, post_id)
        )
        """
    )

    conn.commit()
    conn.close()
    print("✅ Database schema is ready.")


if __name__ == "__main__":
    create_database()
