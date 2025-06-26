import os
from flask import Flask, request, redirect
import requests
import sqlite3

CLIENT_ID = os.getenv("TWITTER_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITTER_CLIENT_SECRET")
FLASK_SECRET = os.getenv("FLASK_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://your-auth-service.onrender.com/callback")  # default if not set

DB_FILE = "bot_data.db"
PORT = 8000

app = Flask(__name__)
app.secret_key = FLASK_SECRET



# ───── REDIRECT TO TWITTER ─────
@app.route("/login")
def login():
    telegram_id = request.args.get("tgid")
    if not telegram_id:
        return "Missing Telegram ID (tgid)", 400

    state = telegram_id  # for later lookup
    url = (
        "https://twitter.com/i/oauth2/authorize?"
        f"response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope=tweet.read%20users.read%20like.read"
        f"&state={state}"
        f"&code_challenge=challenge"
        f"&code_challenge_method=plain"
    )
    return redirect(url)


# ───── HANDLE CALLBACK ─────
@app.route("/callback")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")  # we stored telegram_id in here

    if not code or not state:
        return "Missing code or state", 400

    # Exchange code for token
    token_url = "https://api.twitter.com/2/oauth2/token"
    data = {
        "code": code,
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": "challenge",
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    res = requests.post(token_url, data=data, headers=headers,
                        auth=(CLIENT_ID, CLIENT_SECRET))

    if res.status_code != 200:
        print(res.text)
        return "Failed to get access token", 400

    token_data = res.json()
    access_token = token_data["access_token"]

    # Save to DB
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "UPDATE users SET twitter_access_token = ? WHERE telegram_id = ?",
        (access_token, state)
    )
    conn.commit()
    conn.close()

    return f"✅ Twitter connected! You may now return to Telegram."


if __name__ == "__main__":
    app.run(port=PORT)
