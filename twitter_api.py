# twitter_api.py

import requests


def has_liked_post_user_token(access_token: str, tweet_id: str) -> bool:
    url = "https://api.twitter.com/2/users/me/liked_tweets"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    params = {
        "max_results": 100  # Adjust as needed
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code != 200:
        print("[Twitter API Error]", response.status_code, response.text)
        return False

    tweets = response.json().get("data", [])
    return any(tweet["id"] == tweet_id for tweet in tweets)


def has_liked_post(*args, **kwargs):
    raise NotImplementedError("Use has_liked_post_user_token instead.")
