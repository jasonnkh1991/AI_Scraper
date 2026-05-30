import html
import json
import re
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

import requests
from openai import OpenAI
from supabase import Client, create_client


APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "pzMmk1t7AZ8OKJhfU")
APIFY_TIMEOUT_SECONDS = int(os.getenv("APIFY_TIMEOUT_SECONDS", "90"))
FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", os.getenv("TIER1_FETCH_LIMIT", "60")))
TIER2_FETCH_LIMIT = int(os.getenv("TIER2_FETCH_LIMIT", "15"))
OVERNIGHT_FETCH_LIMIT = int(os.getenv("OVERNIGHT_FETCH_LIMIT", "10"))
QUIET_FETCH_LIMIT = int(os.getenv("QUIET_FETCH_LIMIT", "30"))
QUIET_IMMEDIATE_IMPACT_SCORE = int(os.getenv("QUIET_IMMEDIATE_IMPACT_SCORE", "9"))
QUIET_IMMEDIATE_CONFIDENCE_SCORE = int(os.getenv("QUIET_IMMEDIATE_CONFIDENCE_SCORE", "8"))
DIGEST_LOOKBACK_HOURS = int(os.getenv("DIGEST_LOOKBACK_HOURS", "8"))
MAX_DIGEST_EVENTS = int(os.getenv("MAX_DIGEST_EVENTS", "6"))
LOCAL_TIMEZONE = os.getenv("LOCAL_TIMEZONE", "Asia/Hong_Kong")
STATE_KEY = "last_processed_tweet_id"
PROCESSED_TWEET_IDS_KEY = "processed_tweet_ids"
RECENT_EVENT_FINGERPRINTS_KEY = "recent_event_fingerprints"
LAST_DIGEST_DATE_KEY = "last_overnight_digest_date"
ALERT_ARCHIVE_ENABLED = os.getenv("ALERT_ARCHIVE_ENABLED", "true").lower() in {"1", "true", "yes"}
STUDY_ALERT_TYPES = ["group_alert", "single_alert", "study_only_signal"]
MAX_TRACKED_TWEET_IDS = int(os.getenv("MAX_TRACKED_TWEET_IDS", "500"))
AI_PROCESS_LIMIT = int(os.getenv("AI_PROCESS_LIMIT", os.getenv("MAX_NEW_TWEETS_PER_RUN", "15")))
MAX_NEW_TWEETS_PER_RUN = AI_PROCESS_LIMIT
QUEUE_MAX_ATTEMPTS = int(os.getenv("QUEUE_MAX_ATTEMPTS", "2"))
MAX_AI_FAILURES_PER_RUN = int(os.getenv("MAX_AI_FAILURES_PER_RUN", "3"))
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20"))
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "0"))
EVENT_MEMORY_HOURS = int(os.getenv("EVENT_MEMORY_HOURS", "6"))
MAX_TRACKED_EVENTS = int(os.getenv("MAX_TRACKED_EVENTS", "300"))
MARKET_TIMEZONE = os.getenv("MARKET_TIMEZONE", "America/New_York")
TRUTH_SOCIAL_ENABLED = os.getenv("TRUTH_SOCIAL_ENABLED", "true").lower() in {"1", "true", "yes"}
TRUTH_SOCIAL_ACTOR_ID = os.getenv("TRUTH_SOCIAL_ACTOR_ID", "IWIOv7oeNxfcjTnX5")
TRUTH_SOCIAL_URL = os.getenv("TRUTH_SOCIAL_URL", "https://www.truthsocial.com/realDonaldTrump/")
TRUTH_SOCIAL_FETCH_LIMIT = int(os.getenv("TRUTH_SOCIAL_FETCH_LIMIT", "3"))
TRUTH_SOCIAL_RUN_MINUTES = int(os.getenv("TRUTH_SOCIAL_RUN_MINUTES", "60"))
DEFAULT_TIER1_TWITTER_SEARCH_QUERY = (
    "(from:DeItaone OR from:financialjuice OR from:unusual_whales OR "
    "from:zerohedge OR from:WSJ OR from:CNBC OR from:business OR "
    "from:Reuters OR from:ReutersBiz OR from:Benzinga) "
    "-filter:replies lang:en"
)
DEFAULT_TIER2_TWITTER_SEARCH_QUERY = (
    "(from:elonmusk OR from:sama OR from:satyanadella OR "
    "from:sundarpichai OR from:dylan522p OR from:IanCutress OR "
    "from:tomshardware OR from:StockMKTNewz OR from:KobeissiLetter OR "
    "from:FirstSquawk) "
    "-filter:replies lang:en"
)
DEFAULT_TWITTER_SEARCH_QUERY = DEFAULT_TIER1_TWITTER_SEARCH_QUERY


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
            "confidence_score": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
            },
            "source_quality": {
                "type": "string",
                "enum": ["primary", "reputable_media", "terminal_scrape", "rumor", "unknown"],
            },
            "time_horizon": {
                "type": "string",
                "enum": ["intraday", "days", "weeks", "months", "unclear"],
            },
            "target_sectors": {
                "type": "array",
                "items": {"type": "string"},
            },
            "affected_tickers": {
                "type": "array",
                "items": {"type": "string"},
            },
            "summary_zh": {"type": "string"},
            "original_zh": {"type": "string"},
            "why_it_matters_zh": {"type": "string"},
            "market_mechanism_zh": {"type": "string"},
            "trading_action": {"type": "string"},
            "risk_zh": {"type": "string"},
        },
        "required": [
            "has_market_impact",
            "impact_score",
            "confidence_score",
            "source_quality",
            "time_horizon",
            "target_sectors",
            "affected_tickers",
            "summary_zh",
            "original_zh",
            "why_it_matters_zh",
            "market_mechanism_zh",
            "trading_action",
            "risk_zh",
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


def strip_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = html.unescape(text)
    return " ".join(text.split())


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


def normalize_truth_post(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    post_id = str(get_nested(item, "id", "post.id", "uri") or "")
    content = get_nested(item, "content", "text", "full_text", "post.content")
    text = strip_html(content)
    if not post_id or not text:
        return None

    account = item.get("account") if isinstance(item.get("account"), dict) else {}
    handle = (
        get_nested(item, "account.username", "account.acct", "username", "acct")
        or "realDonaldTrump"
    )
    handle = str(handle).lstrip("@")
    author_name = (
        get_nested(item, "account.display_name", "account.displayName", "displayName", "display_name")
        or "Donald J. Trump"
    )
    created_at = parse_datetime(
        get_nested(item, "created_at", "createdAt", "date", "timestamp")
    )
    url = (
        get_nested(item, "url", "uri", "link")
        or f"https://www.truthsocial.com/@{handle}/posts/{post_id}"
    )

    return {
        "tweet_id": f"truth-{post_id}",
        "tweet_id_int": tweet_id_to_int(post_id),
        "author_handle": f"truth:{handle}",
        "author_name": str(author_name),
        "tweet_text": text,
        "tweet_url": str(url),
        "tweet_created_at": created_at,
        "author_followers": account.get("followers_count") if isinstance(account, dict) else None,
    }


def localized_now(timezone_name: str, now: Optional[datetime] = None) -> datetime:
    timezone_obj = ZoneInfo(timezone_name)
    current = now or datetime.now(timezone_obj)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone_obj)
    return current.astimezone(timezone_obj)


def is_hkt_quiet_window(now: Optional[datetime] = None) -> bool:
    current = localized_now(LOCAL_TIMEZONE, now)
    return 0 <= current.hour < 8


def should_send_overnight_digest(now: Optional[datetime] = None) -> bool:
    if os.getenv("BYPASS_MARKET_WINDOW", "").lower() in {"1", "true", "yes"}:
        return False
    current = localized_now(LOCAL_TIMEZONE, now)
    return current.hour == 8 and current.minute == 7


def is_overnight_window(now: Optional[datetime] = None) -> bool:
    current = localized_now(MARKET_TIMEZONE, now)
    return 0 <= current.hour < 6


def current_x_fetch_limit(now: Optional[datetime] = None) -> int:
    if os.getenv("BYPASS_MARKET_WINDOW", "").lower() in {"1", "true", "yes"}:
        return FETCH_LIMIT
    if is_hkt_quiet_window(now):
        return QUIET_FETCH_LIMIT
    return OVERNIGHT_FETCH_LIMIT if is_overnight_window(now) else FETCH_LIMIT


def should_run_tier2(now: Optional[datetime] = None) -> bool:
    if os.getenv("BYPASS_MARKET_WINDOW", "").lower() in {"1", "true", "yes"}:
        return True

    current = localized_now(MARKET_TIMEZONE, now)
    if is_hkt_quiet_window(now) or is_overnight_window(current):
        return False
    if not should_run_market_window(current):
        return False
    return current.minute == 7


def is_twitter_search_actor() -> bool:
    return APIFY_ACTOR_ID == "pzMmk1t7AZ8OKJhfU" or "twitter-tweets-scraper" in APIFY_ACTOR_ID


def tier_twitter_query(tier: int) -> str:
    if tier == 1:
        return (os.getenv("TIER1_TWITTER_SEARCH_QUERY") or DEFAULT_TIER1_TWITTER_SEARCH_QUERY).strip()
    if tier == 2:
        return (os.getenv("TIER2_TWITTER_SEARCH_QUERY") or DEFAULT_TIER2_TWITTER_SEARCH_QUERY).strip()
    raise ValueError(f"Unsupported Twitter tier: {tier}")


def should_run_truth_social(now: Optional[datetime] = None) -> bool:
    if not TRUTH_SOCIAL_ENABLED:
        return False
    if os.getenv("BYPASS_MARKET_WINDOW", "").lower() in {"1", "true", "yes"}:
        return True

    current = localized_now(MARKET_TIMEZONE, now)
    if is_hkt_quiet_window(now) or is_overnight_window(current):
        return False
    if not should_run_market_window(current):
        return False
    if TRUTH_SOCIAL_RUN_MINUTES <= 15:
        return True
    if TRUTH_SOCIAL_RUN_MINUTES <= 30:
        return current.minute in {7, 37}
    return current.minute == 7


def should_run_market_window(now: Optional[datetime] = None) -> bool:
    if os.getenv("BYPASS_MARKET_WINDOW", "").lower() in {"1", "true", "yes"}:
        return True

    if is_hkt_quiet_window(now):
        current_hkt = localized_now(LOCAL_TIMEZONE, now)
        return current_hkt.minute == 7

    current = localized_now(MARKET_TIMEZONE, now)
    hour = current.hour
    minute = current.minute

    if 6 <= hour < 20:
        return True
    if 20 <= hour < 24:
        return minute in {7, 37}
    if 0 <= hour < 6:
        return minute in {7, 37}
    return False


def cap_new_tweets_for_run(tweets: List[Dict[str, Any]], limit: int = AI_PROCESS_LIMIT) -> List[Dict[str, Any]]:
    if limit <= 0 or len(tweets) <= limit:
        return tweets
    return tweets[:limit]


def queued_row_to_tweet(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tweet_id": str(row["tweet_id"]),
        "tweet_id_int": tweet_id_to_int(str(row.get("tweet_id") or row.get("tweet_id_int") or "0")),
        "author_handle": str(row.get("author_handle") or "unknown"),
        "author_name": str(row.get("author_name") or row.get("author_handle") or "unknown"),
        "tweet_text": str(row.get("tweet_text") or ""),
        "tweet_url": str(row.get("tweet_url") or ""),
        "tweet_created_at": row.get("tweet_created_at"),
        "author_followers": row.get("author_followers"),
        "source": row.get("source") or "x",
    }


def get_supabase() -> Client:
    return create_client(require_env("SUPABASE_URL"), require_env("SUPABASE_KEY"))


def fetch_state_value(supabase: Client, key: str) -> Optional[str]:
    response = (
        supabase.table("system_states")
        .select("value")
        .eq("key", key)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return str(rows[0]["value"]) if rows else None


def save_state_value(supabase: Client, key: str, value: str) -> None:
    (
        supabase.table("system_states")
        .upsert(
            {
                "key": key,
                "value": value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="key",
        )
        .execute()
    )


def fetch_processed_tweet_ids(supabase: Client) -> set[str]:
    try:
        value = fetch_state_value(supabase, PROCESSED_TWEET_IDS_KEY)
        if not value:
            return set()
        data = json.loads(value)
        if not isinstance(data, list):
            return set()
        return {str(item) for item in data if item}
    except Exception:
        logger.exception("Failed to fetch processed tweet ids from Supabase")
        raise


def save_processed_tweet_ids(supabase: Client, tweet_ids: set[str]) -> None:
    ordered = sorted(tweet_ids, key=tweet_id_to_int, reverse=True)[:MAX_TRACKED_TWEET_IDS]
    try:
        save_state_value(supabase, PROCESSED_TWEET_IDS_KEY, json.dumps(ordered))
    except Exception:
        logger.exception("Failed to save processed tweet ids to Supabase")
        raise


def fetch_recent_event_fingerprints(supabase: Client) -> Dict[str, str]:
    try:
        value = fetch_state_value(supabase, RECENT_EVENT_FINGERPRINTS_KEY)
        if not value:
            return {}
        data = json.loads(value)
        if not isinstance(data, dict):
            return {}

        cutoff = datetime.now(timezone.utc) - timedelta(hours=EVENT_MEMORY_HOURS)
        active: Dict[str, str] = {}
        for fingerprint, timestamp in data.items():
            try:
                seen_at = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            except ValueError:
                continue
            if seen_at >= cutoff:
                active[str(fingerprint)] = seen_at.astimezone(timezone.utc).isoformat()
        return active
    except Exception:
        logger.exception("Failed to fetch recent event fingerprints")
        return {}


def save_recent_event_fingerprints(supabase: Client, fingerprints: Dict[str, str]) -> None:
    ordered = sorted(fingerprints.items(), key=lambda item: item[1], reverse=True)[:MAX_TRACKED_EVENTS]
    try:
        save_state_value(supabase, RECENT_EVENT_FINGERPRINTS_KEY, json.dumps(dict(ordered)))
    except Exception:
        logger.exception("Failed to save recent event fingerprints")
        raise


def fetch_last_processed_tweet_id(supabase: Client) -> int:
    try:
        value = fetch_state_value(supabase, STATE_KEY)
        return tweet_id_to_int(value) if value else 0
    except Exception:
        logger.exception("Failed to fetch state from Supabase")
        raise


def save_last_processed_tweet_id(supabase: Client, tweet_id: str) -> None:
    try:
        save_state_value(supabase, STATE_KEY, tweet_id)
    except Exception:
        logger.exception("Failed to save state to Supabase")
        raise


def enqueue_tweets(supabase: Client, tweets: List[Dict[str, Any]]) -> int:
    if not tweets:
        return 0

    rows = []
    for tweet in tweets:
        rows.append({
            "tweet_id": tweet["tweet_id"],
            "tweet_id_int": tweet.get("tweet_id_int") or tweet_id_to_int(tweet.get("tweet_id")),
            "author_handle": tweet.get("author_handle") or "unknown",
            "author_name": tweet.get("author_name") or tweet.get("author_handle") or "unknown",
            "tweet_text": tweet.get("tweet_text") or "",
            "tweet_url": tweet.get("tweet_url") or "",
            "tweet_created_at": tweet.get("tweet_created_at"),
            "author_followers": tweet.get("author_followers"),
            "source": tweet.get("source") or "x",
            "status": "pending",
        })

    try:
        supabase.table("tweet_queue").upsert(
            rows,
            on_conflict="tweet_id",
            ignore_duplicates=True,
        ).execute()
        logger.info("Queued %s fetched tweets with duplicate protection", len(rows))
        return len(rows)
    except Exception:
        logger.exception("Failed to enqueue tweets into Supabase tweet_queue")
        raise


def fetch_pending_queue_tweets(supabase: Client, limit: int = AI_PROCESS_LIMIT) -> List[Dict[str, Any]]:
    try:
        response = (
            supabase.table("tweet_queue")
            .select("tweet_id,tweet_id_int,author_handle,author_name,tweet_text,tweet_url,tweet_created_at,author_followers,source,attempts")
            .eq("status", "pending")
            .lt("attempts", QUEUE_MAX_ATTEMPTS)
            .order("tweet_id_int", desc=False)
            .limit(limit)
            .execute()
        )
        rows = list(response.data or [])
        logger.info("Loaded %s pending tweets from queue for AI processing limit=%s", len(rows), limit)
        return rows
    except Exception:
        logger.exception("Failed to fetch pending tweets from Supabase tweet_queue")
        raise


def mark_queue_processed(supabase: Client, tweet_id: str) -> None:
    try:
        supabase.table("tweet_queue").update({
            "status": "processed",
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
        }).eq("tweet_id", tweet_id).execute()
    except Exception:
        logger.exception("Failed to mark queued tweet processed tweet_id=%s", tweet_id)
        raise


def mark_queue_failed(supabase: Client, row: Dict[str, Any], error: Exception) -> None:
    attempts = int(row.get("attempts") or 0) + 1
    status = "failed" if attempts >= QUEUE_MAX_ATTEMPTS else "pending"
    message = str(error)[:1000]
    try:
        supabase.table("tweet_queue").update({
            "status": status,
            "attempts": attempts,
            "last_error": message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("tweet_id", str(row["tweet_id"])).execute()
        logger.warning(
            "Marked queued tweet tweet_id=%s status=%s attempts=%s error=%s",
            row["tweet_id"],
            status,
            attempts,
            message,
        )
    except Exception:
        logger.exception("Failed to mark queued tweet failed tweet_id=%s", row.get("tweet_id"))
        raise


def fetch_queue_backlog_count(supabase: Client) -> int:
    try:
        response = (
            supabase.table("tweet_queue")
            .select("tweet_id", count="exact")
            .eq("status", "pending")
            .lt("attempts", QUEUE_MAX_ATTEMPTS)
            .limit(1)
            .execute()
        )
        return int(response.count or 0)
    except Exception:
        logger.exception("Failed to count pending tweet_queue rows")
        return -1


def digest_date_key(now: Optional[datetime] = None) -> str:
    return localized_now(LOCAL_TIMEZONE, now).date().isoformat()


def fetch_overnight_digest_rows(supabase: Client, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    end = localized_now(LOCAL_TIMEZONE, now).replace(hour=8, minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=DIGEST_LOOKBACK_HOURS)
    try:
        response = (
            supabase.table("insights")
            .select(
                "tweet_id,author_handle,author_name,tweet_text,tweet_url,tweet_created_at,impact_score,"
                "target_sectors,summary_zh,trading_action,original_zh,why_it_matters_zh,"
                "market_mechanism_zh,affected_tickers,confidence_score,time_horizon,source_quality,risk_zh,inserted_at"
            )
            .gte("inserted_at", start.astimezone(timezone.utc).isoformat())
            .lt("inserted_at", end.astimezone(timezone.utc).isoformat())
            .order("impact_score", desc=True)
            .limit(80)
            .execute()
        )
        return list(response.data or [])
    except Exception:
        logger.exception("Failed to fetch overnight digest rows")
        raise


def row_to_group_record(row: Dict[str, Any]) -> Dict[str, Any]:
    tweet = {
        "tweet_id": str(row.get("tweet_id") or ""),
        "tweet_text": str(row.get("tweet_text") or ""),
        "author_handle": str(row.get("author_handle") or "unknown"),
        "author_name": str(row.get("author_name") or row.get("author_handle") or "unknown"),
        "tweet_url": str(row.get("tweet_url") or ""),
        "tweet_created_at": row.get("tweet_created_at"),
    }
    insight = {
        "impact_score": int(row.get("impact_score") or 1),
        "confidence_score": int(row.get("confidence_score") or 5),
        "source_quality": row.get("source_quality") or "unknown",
        "time_horizon": row.get("time_horizon") or "unclear",
        "target_sectors": row.get("target_sectors") or [],
        "affected_tickers": row.get("affected_tickers") or [],
        "summary_zh": row.get("summary_zh") or "",
        "original_zh": row.get("original_zh") or row.get("tweet_text") or "",
        "why_it_matters_zh": row.get("why_it_matters_zh") or "",
        "market_mechanism_zh": row.get("market_mechanism_zh") or "",
        "trading_action": row.get("trading_action") or "",
        "risk_zh": row.get("risk_zh") or "",
    }
    return {"tweet": tweet, "insight": insight}


def format_digest_source_links(group: List[Dict[str, Any]]) -> str:
    links = []
    for item in group[:3]:
        handle = html.escape(item["tweet"]["author_handle"])
        url = html.escape(item["tweet"].get("tweet_url") or "")
        if url:
            links.append(f'<a href="{url}">@{handle}</a>')
        else:
            links.append(f"@{handle}")
    if len(group) > 3:
        links.append(f"+{len(group) - 3}")
    return " / ".join(links)


def telegram_html_to_markdown(message: str) -> str:
    text = re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', r'\2 (\1)', message)
    text = re.sub(r'</(b|strong|i|em)>', '', text)
    text = re.sub(r'<(b|strong|i|em)>', '', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def group_period(group: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    values = [item["tweet"].get("tweet_created_at") for item in group if item["tweet"].get("tweet_created_at")]
    if not values:
        return None, None
    return min(values), max(values)


def alert_metadata_from_group(group: List[Dict[str, Any]], merged: Dict[str, Any]) -> Dict[str, Any]:
    period_start, period_end = group_period(group)
    confidences = [int(item["insight"].get("confidence_score") or 0) for item in group]
    return {
        "period_start": period_start,
        "period_end": period_end,
        "insight_ids": [str(item["tweet"].get("tweet_id") or "") for item in group if item["tweet"].get("tweet_id")],
        "source_tweet_urls": [str(item["tweet"].get("tweet_url") or "") for item in group if item["tweet"].get("tweet_url")],
        "impact_max": int(merged.get("impact_score") or 0) or None,
        "confidence_avg": round(sum(confidences) / len(confidences), 2) if confidences else None,
        "tickers": sorted({str(ticker).upper() for item in group for ticker in item["insight"].get("affected_tickers", []) if str(ticker).strip()}),
        "sectors": sorted({str(sector) for item in group for sector in item["insight"].get("target_sectors", []) if str(sector).strip()}),
    }


def hkt_day_bounds(study_date: Optional[str] = None, now: Optional[datetime] = None) -> Tuple[datetime, datetime, str]:
    current = localized_now(LOCAL_TIMEZONE, now)
    if study_date:
        year, month, day = [int(part) for part in study_date.split("-")]
        start = datetime(year, month, day, tzinfo=ZoneInfo(LOCAL_TIMEZONE))
    else:
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end, start.date().isoformat()


def hkt_period_label(value: Optional[str]) -> str:
    if not value:
        return "未分類"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(ZoneInfo(LOCAL_TIMEZONE))
    except ValueError:
        return "未分類"
    hour = dt.hour
    if 0 <= hour < 8:
        return "Overnight 00:00-08:00"
    if 8 <= hour < 12:
        return "Morning 08:00-12:00"
    if 12 <= hour < 16:
        return "Midday 12:00-16:00"
    if 16 <= hour < 20:
        return "US Pre-market/Open 16:00-20:00"
    return "US Market 20:00-00:00"


def build_daily_study_markdown(alerts: List[Dict[str, Any]], study_date: str) -> str:
    lines = [
        f"# Daily Market Study Brief - {study_date} HKT",
        "",
        f"Alerts archived: {len(alerts)}",
    ]
    if not alerts:
        lines.append("\nNo archived Telegram alerts for this date yet.")
        return "\n".join(lines)

    by_period: Dict[str, List[Dict[str, Any]]] = {}
    for alert in alerts:
        by_period.setdefault(hkt_period_label(alert.get("period_start") or alert.get("created_at")), []).append(alert)

    for period, items in by_period.items():
        lines.extend(["", f"## {period}"])
        for alert in items:
            tickers = ", ".join(alert.get("tickers") or []) or "N/A"
            sectors = ", ".join(alert.get("sectors") or []) or "N/A"
            sources = alert.get("source_tweet_urls") or []
            lines.extend([
                "",
                f"### {alert.get('title') or alert.get('alert_type')}",
                f"- Type: {alert.get('alert_type')}",
                f"- Impact max: {alert.get('impact_max') or 'N/A'}",
                f"- Confidence avg: {alert.get('confidence_avg') or 'N/A'}",
                f"- Tickers: {tickers}",
                f"- Sectors: {sectors}",
                "",
                str(alert.get("message_markdown") or "").strip(),
            ])
            if sources:
                lines.append("\nSources:")
                lines.extend(f"- {url}" for url in sources[:12])
    return "\n".join(lines).strip()


def refresh_daily_study_brief(supabase: Client, now: Optional[datetime] = None) -> None:
    if not ALERT_ARCHIVE_ENABLED:
        return
    start, end, study_date = hkt_day_bounds(now=now)
    try:
        response = (
            supabase.table("telegram_alerts")
            .select("id,alert_type,session_id,period_start,period_end,title,message_markdown,source_tweet_urls,impact_max,confidence_avg,tickers,sectors,created_at")
            .in_("alert_type", STUDY_ALERT_TYPES)
            .gte("created_at", start.astimezone(timezone.utc).isoformat())
            .lt("created_at", end.astimezone(timezone.utc).isoformat())
            .order("created_at", desc=False)
            .execute()
        )
        alerts = list(response.data or [])
        tickers = sorted({ticker for alert in alerts for ticker in (alert.get("tickers") or [])})
        sectors = sorted({sector for alert in alerts for sector in (alert.get("sectors") or [])})
        urls = []
        seen_urls = set()
        for alert in alerts:
            for url in alert.get("source_tweet_urls") or []:
                if url not in seen_urls:
                    seen_urls.add(url)
                    urls.append(url)
        row = {
            "study_date": study_date,
            "timezone": LOCAL_TIMEZONE,
            "title": f"Daily Market Study Brief - {study_date} HKT",
            "brief_markdown": build_daily_study_markdown(alerts, study_date),
            "alert_ids": [int(alert["id"]) for alert in alerts if alert.get("id") is not None],
            "tickers": tickers,
            "sectors": sectors,
            "source_tweet_urls": urls,
            "alert_count": len(alerts),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        supabase.table("daily_study_briefs").upsert(row, on_conflict="study_date").execute()
    except Exception:
        logger.warning("Daily study brief refresh skipped; archive tables may not exist yet", exc_info=True)


def archive_telegram_alert(
    supabase: Client,
    alert_type: str,
    title: str,
    message_html: str,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    refresh_study: bool = False,
) -> None:
    if not ALERT_ARCHIVE_ENABLED:
        return
    metadata = metadata or {}
    row = {
        "alert_type": alert_type,
        "session_id": session_id,
        "period_start": metadata.get("period_start"),
        "period_end": metadata.get("period_end"),
        "title": title,
        "message_html": message_html,
        "message_markdown": telegram_html_to_markdown(message_html),
        "insight_ids": metadata.get("insight_ids") or [],
        "source_tweet_urls": metadata.get("source_tweet_urls") or [],
        "impact_max": metadata.get("impact_max"),
        "confidence_avg": metadata.get("confidence_avg"),
        "tickers": metadata.get("tickers") or [],
        "sectors": metadata.get("sectors") or [],
    }
    try:
        supabase.table("telegram_alerts").insert(row).execute()
        if refresh_study:
            refresh_daily_study_brief(supabase)
    except Exception:
        logger.warning("Telegram archive insert skipped; archive tables may not exist yet", exc_info=True)


def build_study_only_signal_message(
    group: List[Dict[str, Any]],
    merged: Dict[str, Any],
    index: int,
    total: int,
) -> str:
    sources = " / ".join(f"@{item['tweet']['author_handle']}" for item in group[:6])
    if len(group) > 6:
        sources += f" / +{len(group) - 6}"
    sectors = ", ".join(merged.get("target_sectors") or ["未分類"])
    tickers = ", ".join(merged.get("affected_tickers") or ["未能直接映射"])
    source_links = "\n".join(
        f'- <a href="{html.escape(item["tweet"]["tweet_url"])}">@{html.escape(item["tweet"]["author_handle"])}</a>'
        for item in group[:8]
    )
    return f"""
<b>Study-only 市場訊號 {index}/{total}</b>
<b>狀態：</b>Quiet Mode 已收錄，未即時 Telegram
<b>整合：</b>{len(group)} 條相近 post
<b>來源：</b>{html.escape(sources)}
<b>Impact：</b>{int(merged.get('impact_score', 0))}/10 · <b>Confidence：</b>{int(merged.get('confidence_score', 0))}/10
<b>Source：</b>{html.escape(str(merged.get('source_quality', 'unknown')))} · <b>時窗：</b>{html.escape(str(merged.get('time_horizon', 'unclear')))}
<b>板塊：</b>{html.escape(sectors)}
<b>Ticker：</b>{html.escape(tickers)}

<b>整合重點：</b>
{html.escape(truncate_text(merged.get('summary_zh', ''), 700))}

<b>點解重要：</b>
{html.escape(truncate_text(merged.get('why_it_matters_zh', ''), 700))}

<b>影響鏈：</b>
{html.escape(truncate_text(merged.get('market_mechanism_zh', ''), 700))}

<b>交易觀察：</b>
{html.escape(truncate_text(merged.get('trading_action', ''), 500))}

<b>反面風險：</b>
{html.escape(truncate_text(merged.get('risk_zh', ''), 500))}

<b>Sources：</b>
{source_links}
""".strip()


def archive_study_only_signals(
    supabase: Client,
    groups: List[List[Dict[str, Any]]],
    merged_insights: List[Dict[str, Any]],
    session_id: str,
) -> None:
    for index, (group, merged) in enumerate(zip(groups, merged_insights), start=1):
        archive_telegram_alert(
            supabase,
            "study_only_signal",
            f"Study-only 市場訊號 {index}/{len(groups)}",
            build_study_only_signal_message(group, merged, index, len(groups)),
            session_id=session_id,
            metadata=alert_metadata_from_group(group, merged),
            refresh_study=False,
        )


def build_overnight_digest_message(groups: List[List[Dict[str, Any]]], now: Optional[datetime] = None) -> str:
    current = localized_now(LOCAL_TIMEZONE, now)
    end = current.replace(hour=8, minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=DIGEST_LOOKBACK_HOURS)
    ranked = sorted(
        groups,
        key=lambda group: (
            max(int(item["insight"].get("impact_score", 0)) for item in group),
            max(int(item["insight"].get("confidence_score", 0)) for item in group),
            len(group),
        ),
        reverse=True,
    )[:MAX_DIGEST_EVENTS]

    lines = [
        "<b>━━ Overnight Market Digest ━━</b>",
        f"<b>時段：</b>{html.escape(start.strftime('%Y-%m-%d %H:%M'))}-{html.escape(end.strftime('%H:%M'))} HKT",
        f"<b>整合事件：</b>{len(ranked)} / <b>原始訊號：</b>{sum(len(group) for group in groups)}",
    ]

    for idx, group in enumerate(ranked, start=1):
        merged = merge_group_insight(group)
        tickers = ", ".join(merged.get("affected_tickers") or ["未能直接映射"])
        sectors = ", ".join(merged.get("target_sectors") or ["未分類"])
        lines.extend([
            "",
            f"<b>{idx}. {html.escape(truncate_text(merged.get('summary_zh', ''), 120))}</b>",
            f"Impact {int(merged.get('impact_score', 0))}/10 · Confidence {int(merged.get('confidence_score', 0))}/10 · {html.escape(str(merged.get('time_horizon', 'unclear')))}",
            f"Ticker：{html.escape(tickers)}",
            f"板塊：{html.escape(sectors)}",
            f"重點：{html.escape(truncate_text(merged.get('why_it_matters_zh') or merged.get('market_mechanism_zh') or merged.get('trading_action'), 180))}",
            f"交易觀察：{html.escape(truncate_text(merged.get('trading_action', ''), 160))}",
            f"來源：{format_digest_source_links(group)}",
        ])

    return "\n".join(lines)


def send_overnight_digest_if_due(supabase: Client, now: Optional[datetime] = None) -> None:
    if not should_send_overnight_digest(now):
        return

    today_key = digest_date_key(now)
    if fetch_state_value(supabase, LAST_DIGEST_DATE_KEY) == today_key:
        logger.info("Overnight digest already sent for %s", today_key)
        return

    rows = fetch_overnight_digest_rows(supabase, now)
    records = [row_to_group_record(row) for row in rows]
    if not records:
        message = f"<b>━━ Overnight Market Digest ━━</b>\n今日 HKT 00:00-08:00 暫時未有高衝擊訊號。"
        post_telegram_message(message, disable_preview=True)
        archive_telegram_alert(
            supabase,
            "overnight_digest",
            "Overnight Market Digest",
            message,
            session_id=f"digest-{today_key}",
            metadata={
                "period_start": (localized_now(LOCAL_TIMEZONE, now).replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(hours=DIGEST_LOOKBACK_HOURS)).astimezone(timezone.utc).isoformat(),
                "period_end": localized_now(LOCAL_TIMEZONE, now).replace(hour=8, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat(),
            },
            refresh_study=True,
        )
        save_state_value(supabase, LAST_DIGEST_DATE_KEY, today_key)
        return

    groups = group_high_impact_records(records)
    message = build_overnight_digest_message(groups, now)
    post_telegram_message(message, disable_preview=True)
    metadata = {
        "period_start": (localized_now(LOCAL_TIMEZONE, now).replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(hours=DIGEST_LOOKBACK_HOURS)).astimezone(timezone.utc).isoformat(),
        "period_end": localized_now(LOCAL_TIMEZONE, now).replace(hour=8, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat(),
        "insight_ids": [str(row.get("tweet_id")) for row in rows if row.get("tweet_id")],
        "source_tweet_urls": [str(row.get("tweet_url")) for row in rows if row.get("tweet_url")],
        "impact_max": max((int(row.get("impact_score") or 0) for row in rows), default=0) or None,
        "confidence_avg": round(sum(int(row.get("confidence_score") or 0) for row in rows) / len(rows), 2) if rows else None,
        "tickers": sorted({str(ticker).upper() for row in rows for ticker in (row.get("affected_tickers") or []) if str(ticker).strip()}),
        "sectors": sorted({str(sector) for row in rows for sector in (row.get("target_sectors") or []) if str(sector).strip()}),
    }
    archive_telegram_alert(
        supabase,
        "overnight_digest",
        "Overnight Market Digest",
        message,
        session_id=f"digest-{today_key}",
        metadata=metadata,
        refresh_study=True,
    )
    save_state_value(supabase, LAST_DIGEST_DATE_KEY, today_key)
    logger.info("Overnight digest sent date=%s rows=%s groups=%s", today_key, len(rows), len(groups))


def extract_apify_run_id(response_text: str) -> Optional[str]:
    try:
        body = json.loads(response_text)
        message = str(body.get("error", {}).get("message", ""))
    except json.JSONDecodeError:
        message = response_text

    match = re.search(r"run ID:\s*([A-Za-z0-9_-]+)", message)
    return match.group(1) if match else None


def fetch_apify_run_log(run_id: str, token: str) -> Optional[str]:
    try:
        response = requests.get(
            f"https://api.apify.com/v2/logs/{run_id}",
            params={"token": token},
            timeout=20,
        )
        if not response.ok:
            logger.warning("Could not fetch Apify run log run_id=%s status=%s", run_id, response.status_code)
            return None
        lines = response.text.splitlines()
        return "\n".join(lines[-80:])
    except Exception:
        logger.exception("Could not fetch Apify run log run_id=%s", run_id)
        return None


def build_apify_payload(fetch_limit: Optional[int] = None, query: Optional[str] = None) -> Dict[str, Any]:
    limit = fetch_limit if fetch_limit is not None else current_x_fetch_limit()
    if is_twitter_search_actor():
        search_query = (query or DEFAULT_TWITTER_SEARCH_QUERY).strip()
        if not search_query:
            raise RuntimeError("Missing Twitter search query")
        return {
            "mode": "Advanced Search",
            "query": search_query,
            "query_type": "Latest",
            "max_results": limit,
        }

    list_url = require_env("TWITTER_LIST_URL")
    return {
        "startUrls": [list_url],
        "maxItems": limit,
        "sort": "Latest",
    }


def run_apify_actor(actor_id: str, payload: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    token = require_env("APIFY_TOKEN")
    actor_path = actor_id.replace("/", "~")
    max_total_charge_usd = os.getenv("APIFY_MAX_TOTAL_CHARGE_USD", "").strip()
    if actor_id == TRUTH_SOCIAL_ACTOR_ID:
        max_total_charge_usd = os.getenv("TRUTH_SOCIAL_MAX_TOTAL_CHARGE_USD", max_total_charge_usd or "0.02").strip()

    api_url = (
        f"https://api.apify.com/v2/acts/{actor_path}/run-sync-get-dataset-items"
        f"?token={token}"
        f"&timeout={APIFY_TIMEOUT_SECONDS}"
        f"&maxItems={limit}"
        f"&limit={limit}"
        f"&clean=true"
    )
    if max_total_charge_usd:
        api_url += f"&maxTotalChargeUsd={max_total_charge_usd}"
    logger.info("Running Apify actor=%s fetch_limit=%s payload_keys=%s", actor_id, limit, sorted(payload.keys()))

    try:
        response = requests.post(api_url, json=payload, timeout=APIFY_TIMEOUT_SECONDS + 30)
        if not response.ok:
            logger.error("Apify response: %s", response.text)
            run_id = extract_apify_run_id(response.text)
            if run_id:
                log_tail = fetch_apify_run_log(run_id, token)
                if log_tail:
                    logger.error("Apify run log tail run_id=%s:\n%s", run_id, log_tail)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError(f"Unexpected Apify response shape: {type(data).__name__}")
        logger.info("Apify actor=%s returned %s raw items with maxItems=%s", actor_id, len(data), limit)
        if data:
            logger.info("Apify actor=%s first item keys: %s", actor_id, sorted(data[0].keys()))
        return data
    except Exception:
        logger.exception("Failed to fetch data from Apify actor=%s", actor_id)
        raise


def fetch_tweets_from_apify() -> List[Dict[str, Any]]:
    if not is_twitter_search_actor():
        limit = current_x_fetch_limit()
        logger.info("Using legacy X list fetch limit=%s", limit)
        return run_apify_actor(APIFY_ACTOR_ID, build_apify_payload(limit), limit)

    tier1_limit = current_x_fetch_limit()
    tier1_query = tier_twitter_query(1)
    logger.info("Fetching X Tier 1 limit=%s query=%s", tier1_limit, tier1_query)
    items = run_apify_actor(
        APIFY_ACTOR_ID,
        build_apify_payload(tier1_limit, tier1_query),
        tier1_limit,
    )

    if should_run_tier2():
        tier2_query = tier_twitter_query(2)
        logger.info("Fetching X Tier 2 limit=%s query=%s", TIER2_FETCH_LIMIT, tier2_query)
        items.extend(
            run_apify_actor(
                APIFY_ACTOR_ID,
                build_apify_payload(TIER2_FETCH_LIMIT, tier2_query),
                TIER2_FETCH_LIMIT,
            )
        )
    else:
        logger.info("X Tier 2 fetch skipped for this run.")

    return items


def canonical_truth_social_url(value: str) -> str:
    url = value.strip().rstrip("/")
    url = url.replace("http://", "https://")
    url = url.replace("https://truthsocial.com/", "https://www.truthsocial.com/")

    prefix = "https://www.truthsocial.com/"
    if url.startswith(prefix):
        path = url[len(prefix):].strip("/")
        if path.startswith("@"):
            path = path[1:]
        if path and "/" not in path:
            return f"{prefix}{path}/"
    return url


def fetch_truth_posts_from_apify() -> List[Dict[str, Any]]:
    payload = {
        "startUrls": [canonical_truth_social_url(TRUTH_SOCIAL_URL)],
        "maxItems": TRUTH_SOCIAL_FETCH_LIMIT,
        "monitoringMode": False,
        "maxConcurrency": 1,
        "minConcurrency": 1,
        "maxRequestRetries": int(os.getenv("TRUTH_SOCIAL_MAX_RETRIES", "100")),
    }
    return run_apify_actor(TRUTH_SOCIAL_ACTOR_ID, payload, TRUTH_SOCIAL_FETCH_LIMIT)


def truth_social_diagnostic_payloads() -> List[tuple[str, Dict[str, Any]]]:
    official_url = canonical_truth_social_url(TRUTH_SOCIAL_URL)
    at_url = official_url.replace("https://www.truthsocial.com/", "https://truthsocial.com/@").rstrip("/")
    diagnostic_date = os.getenv("TRUTH_SOCIAL_DIAGNOSTIC_DATE", "").strip()
    if not diagnostic_date:
        diagnostic_date = (datetime.now(timezone.utc) - timedelta(days=14)).date().isoformat()

    base = {
        "maxItems": TRUTH_SOCIAL_FETCH_LIMIT,
        "maxConcurrency": 1,
        "minConcurrency": 1,
        "maxRequestRetries": int(os.getenv("TRUTH_SOCIAL_MAX_RETRIES", "100")),
    }

    return [
        (
            "official-url-no-date",
            {**base, "startUrls": [official_url], "monitoringMode": False},
        ),
        (
            "official-url-with-date",
            {**base, "startUrls": [official_url], "date": diagnostic_date, "monitoringMode": False},
        ),
        (
            "at-url-with-date",
            {**base, "startUrls": [at_url], "date": diagnostic_date, "monitoringMode": False},
        ),
        (
            "official-url-monitoring-mode",
            {**base, "startUrls": [official_url], "date": diagnostic_date, "monitoringMode": True},
        ),
        (
            "official-url-explicit-apify-proxy",
            {
                **base,
                "startUrls": [official_url],
                "date": diagnostic_date,
                "monitoringMode": False,
                "proxy": {"useApifyProxy": True},
            },
        ),
    ]


def run_truth_social_diagnostics() -> int:
    logger.info(
        "Starting Truth Social diagnostics actor=%s limit=%s url=%s",
        TRUTH_SOCIAL_ACTOR_ID,
        TRUTH_SOCIAL_FETCH_LIMIT,
        TRUTH_SOCIAL_URL,
    )
    total_raw_items = 0
    total_normalized_items = 0

    for name, payload in truth_social_diagnostic_payloads():
        logger.info("Truth Social diagnostic case=%s payload=%s", name, json.dumps(payload, sort_keys=True))
        try:
            raw_items = run_apify_actor(TRUTH_SOCIAL_ACTOR_ID, payload, TRUTH_SOCIAL_FETCH_LIMIT)
        except Exception:
            logger.exception("Truth Social diagnostic case=%s failed", name)
            continue

        normalized = [post for item in raw_items if (post := normalize_truth_post(item))]
        total_raw_items += len(raw_items)
        total_normalized_items += len(normalized)
        logger.info(
            "Truth Social diagnostic case=%s raw_items=%s normalized_items=%s",
            name,
            len(raw_items),
            len(normalized),
        )
        for post in normalized[:3]:
            logger.info(
                "Truth Social diagnostic sample case=%s id=%s author=%s created_at=%s text=%s",
                name,
                post["tweet_id"],
                post["author_handle"],
                post.get("tweet_created_at"),
                post["tweet_text"][:220],
            )

    logger.info(
        "Truth Social diagnostic summary raw_items=%s normalized_items=%s",
        total_raw_items,
        total_normalized_items,
    )
    return 0 if total_raw_items else 1


def alert_session_title(count: int, group_count: int) -> str:
    now = datetime.now(ZoneInfo(MARKET_TIMEZONE))
    return (
        f"<b>━━ 新一批市場訊號 ━━</b>\n"
        f"<b>NY：</b>{html.escape(now.strftime('%Y-%m-%d %H:%M'))}\n"
        f"<b>高優先 post：</b>{count} · <b>整合事件：</b>{group_count}\n"
        f"<b>說明：</b>以下係今次 workflow 新偵測到嘅訊號，已盡量合併相近內容。"
    )


def post_telegram_message(message: str, disable_preview: bool = False) -> None:
    bot_token = require_env("TELEGRAM_BOT_TOKEN")
    chat_id = require_env("TELEGRAM_CHAT_ID")

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_preview,
            },
            timeout=20,
        )
        if not response.ok:
            logger.error("Telegram response: %s", response.text)
        response.raise_for_status()
    except Exception:
        logger.exception("Telegram message failed")
        raise


def send_telegram_session_header(supabase: Client, count: int, group_count: int, session_id: str) -> None:
    message = alert_session_title(count, group_count)
    post_telegram_message(message, disable_preview=True)
    archive_telegram_alert(
        supabase,
        "session_header",
        "新一批市場訊號",
        message,
        session_id=session_id,
        refresh_study=False,
    )


def signal_tokens(tweet: Dict[str, Any], insight: Dict[str, Any]) -> set[str]:
    text = " ".join(
        str(value or "")
        for value in (
            tweet.get("tweet_text"),
            insight.get("summary_zh"),
            insight.get("original_zh"),
            insight.get("why_it_matters_zh"),
            insight.get("market_mechanism_zh"),
            " ".join(insight.get("target_sectors") or []),
            " ".join(insight.get("affected_tickers") or []),
        )
    ).lower()
    tokens = set(re.findall(r"[$]?[a-z][a-z0-9._-]{2,}", text))
    stopwords = {
        "the", "and", "for", "with", "from", "that", "this", "have", "has",
        "will", "are", "was", "were", "market", "markets", "source", "tweet",
        "watch", "impact", "risk", "sector", "sectors", "stock", "stocks",
    }
    return {token.lstrip("$") for token in tokens if token not in stopwords}


def records_are_similar(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_insight = left["insight"]
    right_insight = right["insight"]
    left_tickers = set(left_insight.get("affected_tickers") or [])
    right_tickers = set(right_insight.get("affected_tickers") or [])
    if left_tickers and right_tickers and left_tickers.intersection(right_tickers):
        return True

    left_tokens = left["tokens"]
    right_tokens = right["tokens"]
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens.intersection(right_tokens))
    union = len(left_tokens.union(right_tokens))
    return overlap >= 4 and overlap / union >= 0.22


def group_high_impact_records(records: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    groups: List[List[Dict[str, Any]]] = []
    for record in records:
        record["tokens"] = signal_tokens(record["tweet"], record["insight"])
        placed = False
        for group in groups:
            if any(records_are_similar(record, existing) for existing in group):
                group.append(record)
                placed = True
                break
        if not placed:
            groups.append([record])
    return groups


def merge_group_insight(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    insights = [item["insight"] for item in group]
    primary = max(insights, key=lambda item: (int(item["impact_score"]), int(item.get("confidence_score", 0))))
    sectors = sorted({sector for item in insights for sector in item.get("target_sectors", [])})
    tickers = sorted({ticker for item in insights for ticker in item.get("affected_tickers", [])})
    return {
        **primary,
        "impact_score": max(int(item["impact_score"]) for item in insights),
        "confidence_score": max(int(item.get("confidence_score", 5)) for item in insights),
        "target_sectors": sectors,
        "affected_tickers": tickers,
    }


def event_fingerprint(group: List[Dict[str, Any]], merged: Optional[Dict[str, Any]] = None) -> str:
    insight = merged or merge_group_insight(group)
    tickers = sorted(str(ticker).upper().lstrip("$") for ticker in insight.get("affected_tickers", []) if str(ticker).strip())
    if tickers:
        return "tickers:" + ",".join(tickers[:6])

    sectors = sorted(str(sector).lower().strip() for sector in insight.get("target_sectors", []) if str(sector).strip())
    token_sets = [item.get("tokens") or signal_tokens(item["tweet"], item["insight"]) for item in group]
    tokens = sorted(set().union(*token_sets)) if token_sets else []
    core_tokens = [token for token in tokens if token not in {"news", "report", "reports", "update", "shares"}][:8]
    return "topic:" + ",".join((sectors[:3] + core_tokens)[:10])


def mark_event_status(
    groups: List[List[Dict[str, Any]]],
    merged_insights: List[Dict[str, Any]],
    recent_events: Dict[str, str],
) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    statuses: List[Dict[str, Any]] = []
    for group, merged in zip(groups, merged_insights):
        fingerprint = event_fingerprint(group, merged)
        previous = recent_events.get(fingerprint)
        statuses.append({
            "fingerprint": fingerprint,
            "is_update": bool(previous),
            "previous_seen_at": previous,
        })
        recent_events[fingerprint] = now
    return statuses


def truncate_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def synthesize_group_insight(client: OpenAI, group: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(group) == 1:
        return merge_group_insight(group)

    payload = [
        {
            "author": f"@{item['tweet']['author_handle']}",
            "created_at": item["tweet"].get("tweet_created_at"),
            "url": item["tweet"]["tweet_url"],
            "tweet_text": item["tweet"]["tweet_text"],
            "insight": item["insight"],
        }
        for item in group
    ]
    try:
        completion = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a hedge fund macro analyst consolidating multiple posts about the same market event. "
                        "Return one integrated Traditional Chinese alert. Do not repeat duplicate facts. "
                        "Preserve uncertainty and distinguish confirmed facts from unconfirmed reports. "
                        "Use the strongest combined market mechanism, tickers, time horizon, and counter-risk."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            temperature=0.1,
            response_format={
                "type": "json_schema",
                "json_schema": INSIGHT_SCHEMA,
            },
        )
        content = completion.choices[0].message.content
        if not content:
            raise ValueError("OpenAI returned empty group synthesis")
        result = json.loads(content)
        result["impact_score"] = int(result["impact_score"])
        result["confidence_score"] = int(result.get("confidence_score", 5))
        result["target_sectors"] = [str(x) for x in result.get("target_sectors", [])]
        result["affected_tickers"] = [str(x).upper() for x in result.get("affected_tickers", [])]
        return result
    except Exception:
        logger.exception("Group synthesis failed; using deterministic merge")
        return merge_group_insight(group)


def send_telegram_group_alert(
    supabase: Client,
    group: List[Dict[str, Any]],
    merged: Dict[str, Any],
    index: int,
    total: int,
    session_id: str,
    event_status: Optional[Dict[str, Any]] = None,
) -> None:
    score = int(merged["impact_score"])
    confidence = int(merged.get("confidence_score", 5))
    score_emoji = "🔥🔥🔥" if score >= 9 else "🔥🔥"
    sectors = ", ".join(merged.get("target_sectors") or ["未分類"])
    tickers = ", ".join(merged.get("affected_tickers") or ["未能直接映射"])
    sources = " / ".join(
        f"@{item['tweet']['author_handle']}" for item in group[:6]
    )
    if len(group) > 6:
        sources += f" / +{len(group) - 6}"

    originals = "\n\n".join(
        f"<b>{idx}. @{html.escape(item['tweet']['author_handle'])}</b>\n"
        f"{html.escape(truncate_text(item['insight'].get('original_zh') or item['tweet']['tweet_text'], 700))}\n"
        f"<a href=\"{html.escape(item['tweet']['tweet_url'])}\">原文</a>"
        for idx, item in enumerate(group[:4], start=1)
    )
    if len(group) > 4:
        originals += f"\n\n其餘 {len(group) - 4} 條相近 post 已合併，詳情可喺 Dashboard 睇。"

    is_update = bool(event_status and event_status.get("is_update"))
    status_label = "事件更新" if is_update else "全新事件"
    previous_line = (
        f"<b>上次見到：</b>{html.escape(str(event_status.get('previous_seen_at')))}\n"
        if is_update and event_status and event_status.get("previous_seen_at")
        else ""
    )

    message = f"""
<b>{score_emoji} 市場高優先級警報 {index}/{total}</b>
<b>狀態：</b>{status_label}
{previous_line}<b>整合：</b>{len(group)} 條相近 post
<b>來源：</b>{html.escape(sources)}
<b>Impact：</b>{score}/10 · <b>Confidence：</b>{confidence}/10
<b>Source：</b>{html.escape(str(merged.get("source_quality", "unknown")))} · <b>時窗：</b>{html.escape(str(merged.get("time_horizon", "unclear")))}
<b>板塊：</b>{html.escape(sectors)}
<b>Ticker：</b>{html.escape(tickers)}

<b>整合重點：</b>
{html.escape(truncate_text(merged.get("summary_zh", ""), 700))}

<b>點解重要：</b>
{html.escape(truncate_text(merged.get("why_it_matters_zh", ""), 700))}

<b>影響鏈：</b>
{html.escape(truncate_text(merged.get("market_mechanism_zh", ""), 700))}

<b>交易觀察：</b>
{html.escape(truncate_text(merged.get("trading_action", ""), 500))}

<b>反面風險：</b>
{html.escape(truncate_text(merged.get("risk_zh", ""), 500))}

<b>原文翻譯：</b>
{originals}
""".strip()
    post_telegram_message(message, disable_preview=False)
    archive_telegram_alert(
        supabase,
        "group_alert",
        f"市場高優先級警報 {index}/{total}",
        message,
        session_id=session_id,
        metadata=alert_metadata_from_group(group, merged),
        refresh_study=False,
    )


def evaluate_tweet(client: OpenAI, tweet: Dict[str, Any]) -> Dict[str, Any]:
    system_prompt = (
        "You are a cynical, highly analytical hedge fund macro analyst writing for an active investor. "
        "Filter aggressively: ignore lifestyle chatter, engagement bait, stale news, memes, vague rumors, "
        "generic political outrage, and duplicate noise unless it changes market odds. "
        "Prioritize concrete catalysts: policy, tariffs, war/energy shocks, SEC filings, 13F/13G, AI infrastructure deals, "
        "earnings/guidance, supply chain constraints, rates/FX/commodities, antitrust/regulation, and named tickers. "
        "Return Traditional Chinese. Be concise but analytical: explain mechanism, impacted tickers, time horizon, confidence, "
        "and the strongest counterargument. Never invent facts that are not in the post; mark uncertainty clearly."
    )
    user_prompt = (
        f"Author: @{tweet['author_handle']} ({tweet['author_name']})\n"
        f"Created at: {tweet.get('tweet_created_at')}\n"
        f"Tweet URL: {tweet['tweet_url']}\n\n"
        f"Tweet:\n{tweet['tweet_text']}\n\n"
        "Decide whether this can plausibly move listed equities, crypto, rates, FX, "
        "commodities, or a clearly identifiable market sector in the near term. "
        "For original_zh, translate the tweet/post into readable Traditional Chinese. "
        "For why_it_matters_zh, explain why an investor should care, not just what happened. "
        "For market_mechanism_zh, describe the transmission path, e.g. policy -> sector demand -> tickers, "
        "or filing -> positioning signal -> valuation narrative. "
        "For affected_tickers, include concrete US tickers when plausible; otherwise use sector names sparingly. "
        "For trading_action, give watchlist/direction/levels of attention, not financial advice. "
        "Set confidence_score lower for unconfirmed source/rumor even if impact_score is high."
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
        result["confidence_score"] = int(result.get("confidence_score", 5))
        result["target_sectors"] = [str(x) for x in result.get("target_sectors", [])]
        result["affected_tickers"] = [str(x).upper() for x in result.get("affected_tickers", [])]
        return result
    except Exception:
        logger.exception("OpenAI evaluation failed for tweet_id=%s", tweet["tweet_id"])
        raise


def send_telegram_alert(tweet: Dict[str, Any], insight: Dict[str, Any], supabase: Optional[Client] = None) -> None:
    score = int(insight["impact_score"])
    confidence = int(insight.get("confidence_score", 5))
    score_emoji = "🔥🔥🔥" if score >= 9 else "🔥🔥"
    sectors = ", ".join(insight.get("target_sectors") or ["未分類"])
    tickers = ", ".join(insight.get("affected_tickers") or ["未能直接映射"])
    message = f"""
<b>{score_emoji} 市場高優先級警報</b>

<b>來源：</b>@{html.escape(tweet["author_handle"])} · {html.escape(tweet["author_name"])}
<b>Impact：</b>{score}/10 · <b>Confidence：</b>{confidence}/10
<b>Source：</b>{html.escape(str(insight.get("source_quality", "unknown")))} · <b>時窗：</b>{html.escape(str(insight.get("time_horizon", "unclear")))}
<b>板塊：</b>{html.escape(sectors)}
<b>Ticker：</b>{html.escape(tickers)}

<b>原文翻譯：</b>
{html.escape(str(insight.get("original_zh") or tweet["tweet_text"]))}

<b>重點：</b>
{html.escape(insight["summary_zh"])}

<b>點解重要：</b>
{html.escape(str(insight.get("why_it_matters_zh", "")))}

<b>影響鏈：</b>
{html.escape(str(insight.get("market_mechanism_zh", "")))}

<b>交易觀察：</b>
{html.escape(insight["trading_action"])}

<b>反面風險：</b>
{html.escape(str(insight.get("risk_zh", "")))}

<a href="{html.escape(tweet["tweet_url"])}">查看原 Tweet</a>
""".strip()

    try:
        post_telegram_message(message, disable_preview=False)
        if supabase is not None:
            archive_telegram_alert(
                supabase,
                "single_alert",
                "市場高優先級警報",
                message,
                session_id=f"single-{tweet['tweet_id']}",
                metadata=alert_metadata_from_group([{"tweet": tweet, "insight": insight}], insight),
                refresh_study=True,
            )
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
        "confidence_score": 10,
        "source_quality": "primary",
        "time_horizon": "intraday",
        "target_sectors": ["System Test"],
        "affected_tickers": [],
        "summary_zh": "系統測試：如果你喺 Telegram、Supabase insights 同 Dashboard 都見到呢條訊息，代表三段鏈路已經打通。",
        "original_zh": "Telegram、Supabase 同 Dashboard 的合成測試記錄。",
        "why_it_matters_zh": "用嚟確認新欄位、深度訊息格式同資料庫寫入都正常。",
        "market_mechanism_zh": "無市場影響；只係系統端到端驗證。",
        "trading_action": "無需交易；呢條係測試訊號，可以驗證後喺 Supabase 刪除。",
        "risk_zh": "無市場風險。",
    }
    send_telegram_alert(tweet, insight, supabase)
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
        "original_zh": insight.get("original_zh"),
        "why_it_matters_zh": insight.get("why_it_matters_zh"),
        "market_mechanism_zh": insight.get("market_mechanism_zh"),
        "affected_tickers": insight.get("affected_tickers", []),
        "confidence_score": insight.get("confidence_score"),
        "time_horizon": insight.get("time_horizon"),
        "source_quality": insight.get("source_quality"),
        "risk_zh": insight.get("risk_zh"),
    }

    try:
        supabase.table("insights").upsert(row, on_conflict="tweet_id").execute()
    except Exception as error:
        message = str(error)
        if any(column in message for column in (
            "original_zh",
            "why_it_matters_zh",
            "market_mechanism_zh",
            "affected_tickers",
            "confidence_score",
            "time_horizon",
            "source_quality",
            "risk_zh",
        )):
            logger.warning("Supabase insights table missing Step 2 columns; retrying legacy insert for tweet_id=%s", tweet["tweet_id"])
            legacy_row = {
                key: row[key]
                for key in (
                    "tweet_id",
                    "author_handle",
                    "author_name",
                    "tweet_text",
                    "tweet_url",
                    "tweet_created_at",
                    "impact_score",
                    "target_sectors",
                    "summary_zh",
                    "trading_action",
                )
            }
            supabase.table("insights").upsert(legacy_row, on_conflict="tweet_id").execute()
            return
        logger.exception("Supabase insert failed for tweet_id=%s", tweet["tweet_id"])
        raise


def main() -> int:
    if os.getenv("TRUTH_SOCIAL_DIAGNOSTIC_MODE", "").lower() in {"1", "true", "yes"}:
        return run_truth_social_diagnostics()

    try:
        supabase = get_supabase()
        processed_tweet_ids = fetch_processed_tweet_ids(supabase)
        recent_events = fetch_recent_event_fingerprints(supabase)
        send_overnight_digest_if_due(supabase)
        if os.getenv("SELF_TEST_MODE", "").lower() in {"1", "true", "yes"}:
            run_self_test(supabase)
            return 0

        if not should_run_market_window():
            logger.info("Outside market monitoring window; skipping Apify/OpenAI run.")
            return 0

        openai_client = OpenAI(
            api_key=require_env("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL") or None,
            timeout=OPENAI_TIMEOUT_SECONDS,
            max_retries=OPENAI_MAX_RETRIES,
        )
        last_processed_id = fetch_last_processed_tweet_id(supabase)
        raw_tweets: List[Dict[str, Any]] = []
        try:
            raw_tweets = fetch_tweets_from_apify()
        except Exception:
            logger.exception("X Apify fetch failed; continuing with existing Supabase queue only.")

        raw_truth_posts: List[Dict[str, Any]] = []
        if should_run_truth_social():
            try:
                raw_truth_posts = fetch_truth_posts_from_apify()
            except Exception:
                logger.exception("Truth Social fetch failed; continuing with X source/queue only.")
        elif TRUTH_SOCIAL_ENABLED:
            logger.info("Truth Social fetch skipped for this run.")
    except Exception:
        return 1

    tweets = [tweet for item in raw_tweets if (tweet := normalize_tweet(item))]
    truth_posts = [post for item in raw_truth_posts if (post := normalize_truth_post(item))]
    tweets.extend(truth_posts)
    logger.info(
        "Normalized %s total items from %s X items and %s Truth Social items",
        len(tweets),
        len(raw_tweets),
        len(raw_truth_posts),
    )
    for tweet in tweets:
        logger.info(
            "Fetched tweet id=%s author=%s created_at=%s",
            tweet["tweet_id"],
            tweet["author_handle"],
            tweet.get("tweet_created_at"),
        )
    tweets.sort(key=lambda tweet: tweet["tweet_id_int"])
    enqueue_tweets(supabase, tweets)
    queue_backlog_count = fetch_queue_backlog_count(supabase)
    queued_rows = fetch_pending_queue_tweets(supabase, AI_PROCESS_LIMIT)

    if not queued_rows:
        logger.info(
            "No queued tweets pending AI. last_processed_tweet_id=%s tracked_seen_ids=%s queue_backlog=%s",
            last_processed_id,
            len(processed_tweet_ids),
            queue_backlog_count,
        )
        return 0

    logger.info(
        "Processing %s queued tweets with AI_PROCESS_LIMIT=%s queue_backlog_before=%s",
        len(queued_rows),
        AI_PROCESS_LIMIT,
        queue_backlog_count,
    )
    fully_processed = True
    latest_processed_tweet_id = str(last_processed_id)
    high_impact_records: List[Dict[str, Any]] = []
    ai_failure_count = 0

    for row in queued_rows:
        tweet = queued_row_to_tweet(row)
        try:
            insight = evaluate_tweet(openai_client, tweet)
            if insight["has_market_impact"] and insight["impact_score"] >= 7:
                insert_insight(supabase, tweet, insight)
                high_impact_records.append({"tweet": tweet, "insight": insight})
                logger.info(
                    "Stored high-impact tweet_id=%s score=%s",
                    tweet["tweet_id"],
                    insight["impact_score"],
                )
            else:
                logger.info("Skipped low-impact tweet_id=%s", tweet["tweet_id"])
            mark_queue_processed(supabase, tweet["tweet_id"])
            latest_processed_tweet_id = tweet["tweet_id"]
            processed_tweet_ids.add(tweet["tweet_id"])
        except Exception as error:
            ai_failure_count += 1
            fully_processed = False
            mark_queue_failed(supabase, row, error)
            logger.exception("AI processing failed for queued tweet_id=%s", tweet["tweet_id"])
            if ai_failure_count >= MAX_AI_FAILURES_PER_RUN:
                logger.error("Stopping AI loop after %s failures in one run", ai_failure_count)
                break

    if high_impact_records:
        try:
            quiet_mode = is_hkt_quiet_window()
            telegram_records = [
                record for record in high_impact_records
                if not quiet_mode
                or (
                    int(record["insight"].get("impact_score", 0)) >= QUIET_IMMEDIATE_IMPACT_SCORE
                    and int(record["insight"].get("confidence_score", 0)) >= QUIET_IMMEDIATE_CONFIDENCE_SCORE
                )
            ]
            telegram_tweet_ids = {record["tweet"]["tweet_id"] for record in telegram_records}
            study_only_records = [
                record for record in high_impact_records
                if quiet_mode and record["tweet"]["tweet_id"] not in telegram_tweet_ids
            ]
            session_id = f"alerts-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            if study_only_records:
                study_groups = group_high_impact_records(study_only_records)
                study_merged = [synthesize_group_insight(openai_client, group) for group in study_groups]
                archive_study_only_signals(supabase, study_groups, study_merged, session_id)
                logger.info(
                    "Quiet mode archived %s high-impact records as %s study-only groups",
                    len(study_only_records),
                    len(study_groups),
                )
            if not telegram_records:
                logger.info("Quiet mode suppressed %s high-impact Telegram alerts", len(high_impact_records))
                groups = []
            else:
                groups = group_high_impact_records(telegram_records)
            logger.info("Sending %s Telegram-eligible high-impact records as %s groups", len(telegram_records), len(groups))
            if groups:
                send_telegram_session_header(supabase, len(telegram_records), len(groups), session_id)
                merged_insights = [synthesize_group_insight(openai_client, group) for group in groups]
                event_statuses = mark_event_status(groups, merged_insights, recent_events)
                for index, (group, merged, event_status) in enumerate(zip(groups, merged_insights, event_statuses), start=1):
                    send_telegram_group_alert(supabase, group, merged, index, len(groups), session_id, event_status)
            if groups or study_only_records:
                refresh_daily_study_brief(supabase)
        except Exception:
            return 1

    try:
        save_last_processed_tweet_id(supabase, latest_processed_tweet_id)
        save_processed_tweet_ids(supabase, processed_tweet_ids)
        save_recent_event_fingerprints(supabase, recent_events)
        logger.info(
            "Saved %s=%s tracked_seen_ids=%s tracked_events=%s queue_backlog_after=%s",
            STATE_KEY,
            latest_processed_tweet_id,
            len(processed_tweet_ids),
            len(recent_events),
            fetch_queue_backlog_count(supabase),
        )
    except Exception:
        return 1

    if not fully_processed:
        logger.warning(
            "Batch had %s transient AI failures; affected queued rows were retained or marked failed by attempts.",
            ai_failure_count,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
