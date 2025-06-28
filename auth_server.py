import os
from flask import Flask, request, redirect, session
import requests
import sqlite3
from dotenv import load_dotenv
import logging
import hashlib
import base64
import secrets
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Configuration
CLIENT_ID = os.getenv("TWITTER_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITTER_CLIENT_SECRET")
FLASK_SECRET = os.getenv("FLASK_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
DB_FILE = "bot_data.db"
PORT = 8000

app = Flask(__name__)
app.secret_key = FLASK_SECRET


def generate_pkce():
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().replace("=", "")
    return code_verifier, code_challenge


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def get_twitter_user_info(access_token: str):
    """Fetch authenticated user's Twitter info"""
    url = "https://api.twitter.com/2/users/me"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "TwitterAuth/1.0"
    }
    params = {"user.fields": "username,id"}

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch user info: {str(e)}")
        return None


@app.route("/login")
def login():
    telegram_id = request.args.get("tgid")
    if not telegram_id:
        return "Missing Telegram ID", 400

    # Generate PKCE codes
    code_verifier, code_challenge = generate_pkce()
    session['code_verifier'] = code_verifier
    session['telegram_id'] = telegram_id

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


@app.route("/callback")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")

    if not code or not state or state != session.get('telegram_id'):
        return "Invalid request", 400

    token_url = "https://api.twitter.com/2/oauth2/token"
    data = {
        "code": code,
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": session['code_verifier']  # PKCE verifier
    }

    # Include client secret in Basic Auth header
    auth_header = base64.b64encode(
        f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
    ).decode()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {auth_header}"
    }

    try:
        response = requests.post(token_url, data=data, headers=headers)
        response.raise_for_status()  # Will raise HTTPError for 4XX/5XX
        token_data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Token exchange failed: {str(e)}")
        logger.error(
            f"Response: {e.response.text if hasattr(e, 'response') else ''}")
        return "Failed to authenticate with Twitter", 400

    access_token = token_data["access_token"]

    # Fetch Twitter user info
    user_info = get_twitter_user_info(access_token)
    if not user_info:
        return "Failed to fetch your Twitter account info", 400

    twitter_handle = user_info["data"]["username"]
    twitter_id = user_info["data"]["id"]

    # Save to database
    try:
        conn = get_db_connection()

        # Check if twitter_id column exists
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'twitter_id' in columns:
            conn.execute(
                """UPDATE users 
                SET twitter_access_token = ?,
                    twitter_handle = ?,
                    twitter_id = ?
                WHERE telegram_id = ?""",
                (access_token, twitter_handle, twitter_id, state)
            )
        else:
            # Fallback without twitter_id
            conn.execute(
                """UPDATE users 
                SET twitter_access_token = ?,
                    twitter_handle = ?
                WHERE telegram_id = ?""",
                (access_token, twitter_handle, state)
            )

        conn.commit()
        logger.info(f"Twitter credentials saved for user {state}")
        return f"✅ Twitter connected! Handle: @{twitter_handle}"

    except sqlite3.Error as e:
        logger.error(f"Database error: {str(e)}")
        return "Failed to save credentials", 500
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(port=PORT, debug=True)
