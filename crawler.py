import html
import json
import logging
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

import requests
from openai import OpenAI
from supabase import Client, create_client


APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "pzMmk1t7AZ8OKJhfU")
APIFY_TIMEOUT_SECONDS = int(os.getenv("APIFY_TIMEOUT_SECONDS", "180"))
FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", "5"))
STATE_KEY = "last_processed_tweet_id"
MARKET_TIMEZONE = os.getenv("MARKET_TIMEZONE", "America/New_York")
DEFAULT_TWITTER_SEARCH_QUERY = (
    "(from:realDonaldTrump OR from:TrumpDailyPosts OR from:RNCResearch OR "
    "from:Acyn OR from:DeitaOne OR from:FinancialJuice OR "
    "from:unusual_whales OR from:dylan522p OR from:IanCutress OR "
    "from:tomshardware OR from:elonmusk OR from:samaltman OR "
    "from:satyanadella OR from:sundarpichai OR from:POTUS) "
    "-filter:replies lang:en"
)


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("financial-insight-crawler")


INSIGHT_SCHEMA = {
    "name": "market_impact_evaluation",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "has_market_impact": {"type": "boolean"},
            "impact_score": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
            },
            "target_sectors": {
                "type": "array",
                "items": {"type": "string"},
            },
            "summary_zh": {"type": "string"},
            "trading_action": {"type": "string"},
        },
        "required": [
            "has_market_impact",
            "impact_score",
            "target_sectors",
            "summary_zh",
            "trading_action",
        ],
    },
}


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def tweet_id_to_int(value: Optional[str]) -> int:
    if not value:
        return 0
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else 0


def parse_datetime(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(timezone.utc).isoformat()
    except ValueError:
        return value


def get_nested(data: Dict[str, Any], *paths: str) -> Optional[Any]:
    for path in paths:
        current: Any = data
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if current not in (None, ""):
            return current
    return None


def normalize_tweet(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tweet_id = str(
        get_nested(item, "id", "tweet_id", "tweetId", "rest_id", "legacy.id_str") or ""
    )
    text = get_nested(
        item,
        "text",
        "fullText",
        "full_text",
        "legacy.full_text",
        "content",
        "tweet.text",
        "tweet.full_text",
    )
    if not tweet_id or not text:
        return None

    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    handle = (
        get_nested(
            item,
            "author.userName",
            "author.username",
            "author.screen_name",
            "author.handle",
            "user.username",
            "user.screen_name",
            "user.handle",
        )
        or item.get("username")
        or item.get("userName")
        or item.get("screen_name")
        or item.get("handle")
        or "unknown"
    )
    handle = str(handle).lstrip("@")
    author_name = (
        get_nested(item, "author.name", "author.displayName", "user.name", "user.displayName")
        or item.get("authorName")
        or item.get("name")
        or handle
    )
    tweet_url = (
        item.get("url")
        or item.get("twitterUrl")
        or item.get("tweetUrl")
        or item.get("link")
        or f"https://x.com/{handle}/status/{tweet_id}"
    )

    return {
        "tweet_id": tweet_id,
        "tweet_id_int": tweet_id_to_int(tweet_id),
        "author_handle": handle,
        "author_name": str(author_name),
        "tweet_text": str(text),
        "tweet_url": str(tweet_url),
        "tweet_created_at": parse_datetime(
            item.get("createdAt") or item.get("created_at") or item.get("date") or item.get("timestamp")
        ),
        "author_followers": author.get("followers") if isinstance(author, dict) else None,
    }


def should_run_market_window(now: Optional[datetime] = None) -> bool:
    if os.getenv("BYPASS_MARKET_WINDOW", "").lower() in {"1", "true", "yes"}:
        return True

    current = now or datetime.now(ZoneInfo(MARKET_TIMEZONE))
    hour = current.hour
    minute = current.minute

    if 6 <= hour < 20:
        return True
    if 20 <= hour < 24:
        return minute in {7, 37}
    return False


def get_supabase() -> Client:
    return create_client(require_env("SUPABASE_URL"), require_env("SUPABASE_KEY"))


def fetch_last_processed_tweet_id(supabase: Client) -> int:
    try:
        response = (
            supabase.table("system_states")
            .select("value")
            .eq("key", STATE_KEY)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return tweet_id_to_int(rows[0]["value"]) if rows else 0
    except Exception:
        logger.exception("Failed to fetch state from Supabase")
        raise


def save_last_processed_tweet_id(supabase: Client, tweet_id: str) -> None:
    try:
        (
            supabase.table("system_states")
            .upsert(
                {
                    "key": STATE_KEY,
                    "value": tweet_id,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="key",
            )
            .execute()
        )
    except Exception:
        logger.exception("Failed to save state to Supabase")
        raise


def build_apify_payload() -> Dict[str, Any]:
    if APIFY_ACTOR_ID == "pzMmk1t7AZ8OKJhfU" or "twitter-tweets-scraper" in APIFY_ACTOR_ID:
        query = os.getenv("TWITTER_SEARCH_QUERY", DEFAULT_TWITTER_SEARCH_QUERY).strip()
        if not query:
            raise RuntimeError("Missing TWITTER_SEARCH_QUERY")
        return {
            "mode": "Advanced Search",
            "query": query,
            "query_type": "Latest",
            "max_results": FETCH_LIMIT,
        }

    list_url = require_env("TWITTER_LIST_URL")
    return {
        "startUrls": [list_url],
        "maxItems": FETCH_LIMIT,
        "sort": "Latest",
    }


def fetch_tweets_from_apify() -> List[Dict[str, Any]]:
    token = require_env("APIFY_TOKEN")
    actor_path = APIFY_ACTOR_ID.replace("/", "~")
    api_url = (
        f"https://api.apify.com/v2/acts/{actor_path}/run-sync-get-dataset-items"
        f"?token={token}"
        f"&timeout={APIFY_TIMEOUT_SECONDS}"
        f"&maxItems={FETCH_LIMIT}"
        f"&limit={FETCH_LIMIT}"
        f"&clean=true"
    )
    payload = build_apify_payload()
    logger.info("Running Apify actor=%s fetch_limit=%s payload_keys=%s", APIFY_ACTOR_ID, FETCH_LIMIT, sorted(payload.keys()))

    try:
        response = requests.post(api_url, json=payload, timeout=APIFY_TIMEOUT_SECONDS + 30)
        if not response.ok:
            logger.error("Apify response: %s", response.text)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError(f"Unexpected Apify response shape: {type(data).__name__}")
        logger.info("Apify returned %s raw items with maxItems=%s", len(data), FETCH_LIMIT)
        if data:
            logger.info("Apify first item keys: %s", sorted(data[0].keys()))
        return data
    except Exception:
        logger.exception("Failed to fetch tweets from Apify")
        raise


def evaluate_tweet(client: OpenAI, tweet: Dict[str, Any]) -> Dict[str, Any]:
    system_prompt = (
        "You are a cynical, highly analytical hedge fund macro analyst. "
        "Your job is to identify only tweets with real market impact. "
        "Ignore lifestyle chatter, engagement bait, vague rumors, stale news, memes, "
        "generic political outrage, and duplicate noise. Be skeptical. "
        "Return Traditional Chinese for summary_zh. Keep it punchy and investor-focused."
    )
    user_prompt = (
        f"Author: @{tweet['author_handle']} ({tweet['author_name']})\n"
        f"Created at: {tweet.get('tweet_created_at')}\n"
        f"Tweet URL: {tweet['tweet_url']}\n\n"
        f"Tweet:\n{tweet['tweet_text']}\n\n"
        "Decide whether this can plausibly move listed equities, crypto, rates, FX, "
        "commodities, or a clearly identifiable market sector in the near term."
    )

    try:
        completion = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format={
                "type": "json_schema",
                "json_schema": INSIGHT_SCHEMA,
            },
        )
        content = completion.choices[0].message.content
        if not content:
            raise ValueError("OpenAI returned empty content")
        result = json.loads(content)
        result["impact_score"] = int(result["impact_score"])
        result["target_sectors"] = [str(x) for x in result.get("target_sectors", [])]
        return result
    except Exception:
        logger.exception("OpenAI evaluation failed for tweet_id=%s", tweet["tweet_id"])
        raise


def send_telegram_alert(tweet: Dict[str, Any], insight: Dict[str, Any]) -> None:
    bot_token = require_env("TELEGRAM_BOT_TOKEN")
    chat_id = require_env("TELEGRAM_CHAT_ID")
    score = int(insight["impact_score"])
    score_emoji = "🔥🔥🔥" if score >= 9 else "🔥🔥"
    sectors = ", ".join(insight.get("target_sectors") or ["未分類"])
    message = f"""
<b>{score_emoji} 市場高優先級警報</b>

<b>來源：</b>@{html.escape(tweet["author_handle"])} · {html.escape(tweet["author_name"])}
<b>Impact：</b>{score}/10
<b>板塊：</b>{html.escape(sectors)}

<b>重點：</b>
{html.escape(insight["summary_zh"])}

<b>交易觀察：</b>
{html.escape(insight["trading_action"])}

<a href="{html.escape(tweet["tweet_url"])}">查看原 Tweet</a>
""".strip()

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=20,
        )
        if not response.ok:
            logger.error("Telegram response: %s", response.text)
        response.raise_for_status()
    except Exception:
        logger.exception("Telegram alert failed for tweet_id=%s", tweet["tweet_id"])
        raise

def run_self_test(supabase: Client) -> None:
    now = datetime.now(timezone.utc)
    tweet = {
        "tweet_id": f"self-test-{now.strftime('%Y%m%d%H%M%S')}",
        "author_handle": "system_test",
        "author_name": "AI Scraper Self Test",
        "tweet_text": "Synthetic test record for Telegram, Supabase, and dashboard verification.",
        "tweet_url": "https://github.com/jasonnkh1991/AI_Scraper/actions",
        "tweet_created_at": now.isoformat(),
    }
    insight = {
        "impact_score": 10,
        "target_sectors": ["System Test"],
        "summary_zh": "系統測試：如果你喺 Telegram、Supabase insights 同 Dashboard 都見到呢條訊息，代表三段鏈路已經打通。",
        "trading_action": "無需交易；呢條係測試訊號，可以驗證後喺 Supabase 刪除。",
    }
    send_telegram_alert(tweet, insight)
    insert_insight(supabase, tweet, insight)
    logger.info("Self-test alert sent and inserted tweet_id=%s", tweet["tweet_id"])


def insert_insight(supabase: Client, tweet: Dict[str, Any], insight: Dict[str, Any]) -> None:
    row = {
        "tweet_id": tweet["tweet_id"],
        "author_handle": tweet["author_handle"],
        "author_name": tweet["author_name"],
        "tweet_text": tweet["tweet_text"],
        "tweet_url": tweet["tweet_url"],
        "tweet_created_at": tweet["tweet_created_at"],
        "impact_score": insight["impact_score"],
        "target_sectors": insight["target_sectors"],
        "summary_zh": insight["summary_zh"],
        "trading_action": insight["trading_action"],
    }

    try:
        supabase.table("insights").upsert(row, on_conflict="tweet_id").execute()
    except Exception:
        logger.exception("Supabase insert failed for tweet_id=%s", tweet["tweet_id"])
        raise


def main() -> int:
    try:
        supabase = get_supabase()
        if os.getenv("SELF_TEST_MODE", "").lower() in {"1", "true", "yes"}:
            run_self_test(supabase)
            return 0

        if not should_run_market_window():
            logger.info("Outside market monitoring window; skipping Apify/OpenAI run.")
            return 0

        openai_client = OpenAI(
            api_key=require_env("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL") or None,
        )
        last_processed_id = fetch_last_processed_tweet_id(supabase)
        raw_tweets = fetch_tweets_from_apify()
    except Exception:
        return 1

    tweets = [tweet for item in raw_tweets if (tweet := normalize_tweet(item))]
    logger.info("Normalized %s tweets from %s Apify items", len(tweets), len(raw_tweets))
    tweets.sort(key=lambda tweet: tweet["tweet_id_int"])
    new_tweets = [tweet for tweet in tweets if tweet["tweet_id_int"] > last_processed_id]

    if not new_tweets:
        logger.info("No new tweets. last_processed_tweet_id=%s", last_processed_id)
        return 0

    logger.info("Processing %s new tweets", len(new_tweets))
    fully_processed = True
    latest_processed_tweet_id = str(last_processed_id)

    for tweet in new_tweets:
        try:
            insight = evaluate_tweet(openai_client, tweet)
            if insight["has_market_impact"] and insight["impact_score"] >= 7:
                send_telegram_alert(tweet, insight)
                insert_insight(supabase, tweet, insight)
                logger.info(
                    "Stored high-impact tweet_id=%s score=%s",
                    tweet["tweet_id"],
                    insight["impact_score"],
                )
            else:
                logger.info("Skipped low-impact tweet_id=%s", tweet["tweet_id"])
            latest_processed_tweet_id = tweet["tweet_id"]
        except Exception:
            fully_processed = False
            logger.exception("Stopped before advancing state past tweet_id=%s", tweet["tweet_id"])
            break

    if fully_processed:
        try:
            save_last_processed_tweet_id(supabase, latest_processed_tweet_id)
            logger.info("Saved %s=%s", STATE_KEY, latest_processed_tweet_id)
        except Exception:
            return 1
    else:
        logger.warning("Batch incomplete; state was not advanced.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
