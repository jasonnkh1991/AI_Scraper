import html
import json
import re
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

import requests
from openai import OpenAI
from supabase import Client, create_client


APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "pzMmk1t7AZ8OKJhfU")
APIFY_TIMEOUT_SECONDS = int(os.getenv("APIFY_TIMEOUT_SECONDS", "180"))
FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", os.getenv("TIER1_FETCH_LIMIT", "40")))
TIER2_FETCH_LIMIT = int(os.getenv("TIER2_FETCH_LIMIT", "20"))
OVERNIGHT_FETCH_LIMIT = int(os.getenv("OVERNIGHT_FETCH_LIMIT", "10"))
STATE_KEY = "last_processed_tweet_id"
PROCESSED_TWEET_IDS_KEY = "processed_tweet_ids"
MAX_TRACKED_TWEET_IDS = int(os.getenv("MAX_TRACKED_TWEET_IDS", "500"))
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


def is_overnight_window(now: Optional[datetime] = None) -> bool:
    current = now or datetime.now(ZoneInfo(MARKET_TIMEZONE))
    return 0 <= current.hour < 6


def current_x_fetch_limit(now: Optional[datetime] = None) -> int:
    if os.getenv("BYPASS_MARKET_WINDOW", "").lower() in {"1", "true", "yes"}:
        return FETCH_LIMIT
    return OVERNIGHT_FETCH_LIMIT if is_overnight_window(now) else FETCH_LIMIT


def should_run_tier2(now: Optional[datetime] = None) -> bool:
    if os.getenv("BYPASS_MARKET_WINDOW", "").lower() in {"1", "true", "yes"}:
        return True

    current = now or datetime.now(ZoneInfo(MARKET_TIMEZONE))
    if is_overnight_window(current):
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

    current = now or datetime.now(ZoneInfo(MARKET_TIMEZONE))
    if is_overnight_window(current):
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

    current = now or datetime.now(ZoneInfo(MARKET_TIMEZONE))
    hour = current.hour
    minute = current.minute

    if 6 <= hour < 20:
        return True
    if 20 <= hour < 24:
        return minute in {7, 37}
    if 0 <= hour < 6:
        return minute in {7, 37}
    return False


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


def send_telegram_session_header(count: int, group_count: int) -> None:
    post_telegram_message(alert_session_title(count, group_count), disable_preview=True)


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


def send_telegram_group_alert(group: List[Dict[str, Any]], merged: Dict[str, Any], index: int, total: int) -> None:
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

    message = f"""
<b>{score_emoji} 市場高優先級警報 {index}/{total}</b>
<b>整合：</b>{len(group)} 條相近 post
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


def send_telegram_alert(tweet: Dict[str, Any], insight: Dict[str, Any]) -> None:
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
        raw_truth_posts: List[Dict[str, Any]] = []
        if should_run_truth_social():
            try:
                raw_truth_posts = fetch_truth_posts_from_apify()
            except Exception:
                logger.exception("Truth Social fetch failed; continuing with X source only.")
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
    new_tweets = [tweet for tweet in tweets if tweet["tweet_id"] not in processed_tweet_ids]

    if not new_tweets:
        logger.info(
            "No unseen tweets. last_processed_tweet_id=%s tracked_seen_ids=%s",
            last_processed_id,
            len(processed_tweet_ids),
        )
        return 0

    logger.info("Processing %s new tweets", len(new_tweets))
    fully_processed = True
    latest_processed_tweet_id = str(last_processed_id)
    high_impact_records: List[Dict[str, Any]] = []

    for tweet in new_tweets:
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
            latest_processed_tweet_id = tweet["tweet_id"]
            processed_tweet_ids.add(tweet["tweet_id"])
        except Exception:
            fully_processed = False
            logger.exception("Stopped before advancing state past tweet_id=%s", tweet["tweet_id"])
            break

    if fully_processed and high_impact_records:
        try:
            groups = group_high_impact_records(high_impact_records)
            logger.info("Sending %s high-impact records as %s Telegram groups", len(high_impact_records), len(groups))
            send_telegram_session_header(len(high_impact_records), len(groups))
            for index, group in enumerate(groups, start=1):
                merged = synthesize_group_insight(openai_client, group)
                send_telegram_group_alert(group, merged, index, len(groups))
        except Exception:
            return 1

    if fully_processed:
        try:
            save_last_processed_tweet_id(supabase, latest_processed_tweet_id)
            save_processed_tweet_ids(supabase, processed_tweet_ids)
            logger.info(
                "Saved %s=%s and tracked_seen_ids=%s",
                STATE_KEY,
                latest_processed_tweet_id,
                len(processed_tweet_ids),
            )
        except Exception:
            return 1
    else:
        logger.warning("Batch incomplete; state was not advanced.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
