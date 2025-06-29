import os
import sqlite3
import logging
import requests
import secrets
import hashlib
import base64
import telegram
from flask import Flask, request, redirect, session
from dotenv import load_dotenv
from threading import Thread
from datetime import datetime, timedelta

# ─── Load Environment ───────────────────────────────────────
load_dotenv()

CLIENT_ID = os.getenv("TWITTER_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITTER_CLIENT_SECRET")
FLASK_SECRET = os.getenv("FLASK_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_FILE = "bot_data.db"
PORT = 8000

# ─── Flask Setup ────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = FLASK_SECRET

# ─── Logging Setup ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ─── Utility: PKCE Generator ────────────────────────────────


def generate_pkce():
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().replace("=", "")
    return code_verifier, code_challenge

# ─── Utility: DB Connection ─────────────────────────────────


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# ─── Utility: Notify Telegram ───────────────────────────────


def notify_telegram(telegram_id: int, twitter_handle: str):
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        bot.send_message(
            chat_id=telegram_id,
            text=f"✅ Twitter connected successfully!\n\n"
            f"Your handle: @{twitter_handle}\n"
            f"You can now participate in raids.",
            parse_mode="Markdown"
        )
        logger.info(f"Successfully notified Telegram user {telegram_id}")
    except Exception as e:
        logger.error(f"Failed to notify Telegram: {str(e)}")

# ─── Utility: Fetch Twitter User Info ───────────────────────


def get_twitter_user_info(access_token: str):
    url = "https://api.twitter.com/2/users/me"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "TwitterAuthBot/1.0"
    }
    params = {"user.fields": "username,id"}

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch user info: {str(e)}")
        return None

# ─── OAuth Login Redirect ───────────────────────────────────


@app.route("/login")
def login():
    telegram_id = request.args.get("tgid")
    if not telegram_id:
        return "Missing Telegram ID", 400

    # Generate PKCE codes
    code_verifier, code_challenge = generate_pkce()
    session["code_verifier"] = code_verifier
    session["telegram_id"] = telegram_id

    auth_url = (
        "https://twitter.com/i/oauth2/authorize?"
        f"response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope=tweet.read%20users.read%20like.read"
        f"&state={telegram_id}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    return redirect(auth_url)

# ─── OAuth Callback Handler ─────────────────────────────────


@app.route("/callback")
def callback():
    # Validate callback parameters
    code = request.args.get("code")
    state = request.args.get("state")
    telegram_id = session.get("telegram_id")

    if not code or not state or state != telegram_id:
        logger.error(f"Invalid callback request: code={code}, state={state}")
        return "Invalid callback request", 400

    # Exchange code for tokens
    token_url = "https://api.twitter.com/2/oauth2/token"
    data = {
        "code": code,
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": session.get("code_verifier")
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": "Basic " + base64.b64encode(
            f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
        ).decode()
    }

    try:
        # Get access token from Twitter
        response = requests.post(token_url, data=data, headers=headers)
        response.raise_for_status()
        token_data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Token exchange failed: {str(e)}")
        return "Twitter authentication failed", 400

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)

    # Calculate expiration time
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    # Get user info from Twitter
    user_info = get_twitter_user_info(access_token)
    if not user_info:
        return "Could not retrieve your Twitter info", 400

    twitter_id = user_info["data"]["id"]
    twitter_handle = user_info["data"]["username"]

    print("Saving Twitter info:", telegram_id, twitter_handle,
          twitter_id, refresh_token, access_token, expires_at)

    # Save to database
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check for required columns
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]

        if "twitter_id" in columns and "token_expires_at" in columns:
            cursor.execute(
                """UPDATE users SET 
                    twitter_access_token = ?,
                    twitter_refresh_token = ?,
                    twitter_handle = ?,
                    twitter_id = ?,
                    token_expires_at = ?
                   WHERE telegram_id = ?""",
                (access_token, refresh_token, twitter_handle,
                 twitter_id, expires_at, telegram_id)
            )
        else:
            # Fallback for older schema
            cursor.execute(
                """UPDATE users SET 
                    twitter_access_token = ?,
                    twitter_handle = ?
                   WHERE telegram_id = ?""",
                (access_token, twitter_handle, telegram_id)
            )

        conn.commit()
        logger.info(
            f"Twitter credentials saved for Telegram user {telegram_id}")

        # Notify user in Telegram
        Thread(target=notify_telegram, args=(
            telegram_id, twitter_handle)).start()

        # Return success page
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Twitter Connection Successful</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; padding: 40px; }}
                .success {{ color: #4CAF50; font-size: 24px; }}
                .handle {{ font-weight: bold; color: #1DA1F2; }}
            </style>
        </head>
        <body>
            <div class="success">✅ Twitter Connected Successfully!</div>
            <p>Your account <span class="handle">@{twitter_handle}</span> is now linked.</p>
            <p>You can safely close this window and return to Telegram.</p>
            <script>
                setTimeout(function() {{
                    window.close();
                }}, 3000);
            </script>
        </body>
        </html>
        """

    except sqlite3.Error as e:
        logger.error(f"Database error: {str(e)}")
        return "Database error occurred", 500
    finally:
        conn.close()


# ─── Server Start ───────────────────────────────────────────
if __name__ == "__main__":
    app.run(port=PORT, debug=True)
