import sqlite3

DB_FILE = "bot_data.db"
TELEGRAM_ID = 6229232611  # Replace with the user ID you want to check

conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

cursor.execute("""
    SELECT telegram_id, twitter_handle, twitter_access_token
    FROM users WHERE telegram_id = ?
""", (TELEGRAM_ID,))

row = cursor.fetchone()

if row:
    print("✅ User found:")
    print(f"Telegram ID: {row[0]}")
    print(f"Twitter Handle: {row[1]}")
    print(f"Access Token: {row[2][:10]}..." if row[2] else "No token saved")
else:
    print("❌ User not found.")

conn.close()
