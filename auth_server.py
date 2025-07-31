from flask import Flask, request, redirect, session
from requests_oauthlib import OAuth1Session
import sqlite3
import os
import requests

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Twitter API credentials
TWITTER_API_KEY = "cM1bezvxdcOiZBh9Ta9D6qxe0"
TWITTER_API_SECRET = "bRA3ExdjS73SDWKoDv58WJPhzbfGcvPWyK5dH38b8zrl09RBJx"
CALLBACK_URL = "https://telegram-bot-production-d526.up.railway.app/twitter/callback"

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")


def save_twitter_account(telegram_id, twitter_handle, access_token, access_token_secret):
    conn = sqlite3.connect("bot_data.db")
    cur = conn.cursor()
    cur.execute("""
        UPDATE users
        SET twitter_handle = ?, access_token = ?, access_token_secret = ?, last_updated = CURRENT_TIMESTAMP
        WHERE telegram_id = ?
    """, (twitter_handle, access_token, access_token_secret, telegram_id))
    conn.commit()
    conn.close()


@app.route('/twitter/connect')
def connect_twitter():
    telegram_id = request.args.get('chat_id')
    if not telegram_id:
        return "Missing chat_id", 400

    session['telegram_id'] = telegram_id

    oauth = OAuth1Session(
        TWITTER_API_KEY,
        client_secret=TWITTER_API_SECRET,
        callback_uri=CALLBACK_URL
    )

    try:
        fetch_response = oauth.fetch_request_token(
            "https://api.twitter.com/oauth/request_token")
    except Exception as e:
        import traceback
        print("⚠️ Detailed error fetching request token:")
        print(traceback.format_exc())
        return f"Failed to get request token: {e}", 500

    session['request_token'] = fetch_response.get('oauth_token')
    session['request_token_secret'] = fetch_response.get('oauth_token_secret')

    auth_url = oauth.authorization_url(
        "https://api.twitter.com/oauth/authorize")
    return redirect(auth_url)


@app.route('/twitter/callback')
def twitter_callback():
    oauth_verifier = request.args.get('oauth_verifier')
    if not oauth_verifier:
        return "Authorization failed: Missing oauth_verifier", 400

    request_token = session.get('request_token')
    request_token_secret = session.get('request_token_secret')
    telegram_id = session.get('telegram_id')

    if not all([request_token, request_token_secret, telegram_id]):
        return "Session expired. Try again.", 400

    oauth = OAuth1Session(
        TWITTER_API_KEY,
        client_secret=TWITTER_API_SECRET,
        resource_owner_key=request_token,
        resource_owner_secret=request_token_secret,
        verifier=oauth_verifier
    )

    try:
        oauth_tokens = oauth.fetch_access_token(
            "https://api.twitter.com/oauth/access_token")
    except Exception as e:
        print(f"Access token error: {e}")
        return "Failed to get access token", 500

    twitter_handle = oauth_tokens.get('screen_name')
    access_token = oauth_tokens.get('oauth_token')
    access_token_secret = oauth_tokens.get('oauth_token_secret')

    save_twitter_account(telegram_id, twitter_handle,
                         access_token, access_token_secret)

    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(telegram_url, json={
            "chat_id": telegram_id,
            "text": f"✅ Twitter account @{twitter_handle} connected successfully!"
        })
    except Exception as e:
        print(f"Telegram API error: {e}")

    return "Twitter account connected! You can close this window."


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
