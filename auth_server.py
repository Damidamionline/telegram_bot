import os
import sqlite3
import logging
import requests
import secrets
import hashlib
import base64
from flask import Flask, request, redirect, session
from dotenv import load_dotenv

# ─── Load Environment ───────────────────────────────────────
load_dotenv()

CLIENT_ID = os.getenv("TWITTER_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITTER_CLIENT_SECRET")
FLASK_SECRET = os.getenv("FLASK_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
DB_FILE = "bot_data.db"
PORT = 8000
print("🔍 ENV Loaded:", CLIENT_ID, REDIRECT_URI)

# ─── Flask Setup ────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = FLASK_SECRET

# ─── Logging Setup ──────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
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

# ─── Utility: Fetch Twitter User Info ───────────────────────


def get_twitter_user_info(access_token: str):
    url = "https://api.twitter.com/2/users/me"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "TwitterAuthBot"
    }
    params = {"user.fields": "username,id"}

    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch user info: {str(e)}")
        return None

# ─── OAuth Login Redirect ───────────────────────────────────


@app.route("/login")
def login():
    telegram_id = request.args.get("tgid")
    if not telegram_id:
        return "Missing Telegram ID", 400

    # Generate PKCE
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
    code = request.args.get("code")
    state = request.args.get("state")

    if not code or not state or state != session.get("telegram_id"):
        return "Invalid callback request", 400

    # Token exchange
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
            f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    }

    try:
        response = requests.post(token_url, data=data, headers=headers)
        response.raise_for_status()
        token_data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Token exchange failed: {e}")
        return "Twitter authentication failed", 400

    access_token = token_data["access_token"]
    user_info = get_twitter_user_info(access_token)

    if not user_info:
        return "Could not retrieve your Twitter info", 400

    twitter_id = user_info["data"]["id"]
    twitter_handle = user_info["data"]["username"]
    telegram_id = state

    try:
        conn = get_db_connection()
        c = conn.cursor()

        # Check for twitter_id column
        c.execute("PRAGMA table_info(users)")
        col_names = [col[1] for col in c.fetchall()]

        if "twitter_id" in col_names:
            c.execute(
                """UPDATE users SET 
                    twitter_access_token = ?, 
                    twitter_handle = ?, 
                    twitter_id = ? 
                   WHERE telegram_id = ?""",
                (access_token, twitter_handle, twitter_id, telegram_id)
            )
        else:
            c.execute(
                """UPDATE users SET 
                    twitter_access_token = ?, 
                    twitter_handle = ? 
                   WHERE telegram_id = ?""",
                (access_token, twitter_handle, twitter_id, state)
            )

        conn.commit()
        logger.info(f"Twitter credentials saved for user {state}")
        return f"✅ Twitter connected successfully! Handle: @{twitter_handle}"

    except sqlite3.Error as db_err:
        logger.error(f"Database error: {db_err}")
        return "Database error occurred", 500

    finally:
        conn.close()


# ─── Server Start ───────────────────────────────────────────
if __name__ == "__main__":
    app.run(port=PORT, debug=True)
