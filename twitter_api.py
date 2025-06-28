import requests
import logging
from typing import Optional, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TwitterAPI:
    @staticmethod
    def verify_user_identity(access_token: str) -> Optional[Dict[str, Any]]:
        """Verify the access token and return user info"""
        url = "https://api.twitter.com/2/users/me"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "TwitterVerify/1.0"
        }
        params = {"user.fields": "username,id"}

        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Identity verification failed: {str(e)}")
            return None

    @staticmethod
    def has_liked_tweet(access_token: str, tweet_id: str) -> bool:
        """Check if authenticated user liked a specific tweet"""
        # First get user ID from token
        user_info = TwitterAPI.verify_user_identity(access_token)
        if not user_info:
            return False

        user_id = user_info["data"]["id"]

        # Check user's liked tweets
        url = f"https://api.twitter.com/2/users/{user_id}/liked_tweets"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "TwitterLikeCheck/1.0"
        }
        params = {
            "max_results": 100,
            "tweet.fields": "id"
        }

        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()

            liked_tweets = response.json().get("data", [])
            return any(tweet["id"] == tweet_id for tweet in liked_tweets)

        except requests.exceptions.RequestException as e:
            logger.error(f"Like check failed for tweet {tweet_id}: {str(e)}")
            return False

    @staticmethod
    def get_tweet_info(tweet_id: str, bearer_token: str) -> Optional[Dict[str, Any]]:
        """Fetch public tweet information"""
        url = f"https://api.twitter.com/2/tweets/{tweet_id}"
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "User-Agent": "TwitterInfo/1.0"
        }
        params = {
            "tweet.fields": "author_id,public_metrics",
            "expansions": "author_id"
        }

        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch tweet {tweet_id}: {str(e)}")
            return None

# Legacy function for backward compatibility


def has_liked_post_user_token(access_token: str, tweet_id: str) -> bool:
    return TwitterAPI.has_liked_tweet(access_token, tweet_id)
