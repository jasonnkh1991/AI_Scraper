import html
import json
import logging
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

import requests
from supabase import Client, create_client

logger = logging.getLogger("polymarket-radar")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)

GAMMA_BASE_URL = os.getenv("POLYMARKET_GAMMA_BASE_URL", "https://gamma-api.polymarket.com").rstrip("/")
POLYMARKET_BASE_URL = os.getenv("POLYMARKET_BASE_URL", "https://polymarket.com").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("POLYMARKET_REQUEST_TIMEOUT_SECONDS", "20"))
POLYMARKET_ENABLED = os.getenv("POLYMARKET_ENABLED", "true").lower() in {"1", "true", "yes"}
POLYMARKET_DISCOVERY_ENABLED = os.getenv("POLYMARKET_DISCOVERY_ENABLED", "true").lower() in {"1", "true", "yes"}
POLYMARKET_EXTERNAL_DISCOVERY_ENABLED = os.getenv("POLYMARKET_EXTERNAL_DISCOVERY_ENABLED", "true").lower() in {"1", "true", "yes"}
POLYMARKET_APIFY_FALLBACK_ENABLED = os.getenv("POLYMARKET_APIFY_FALLBACK_ENABLED", "false").lower() in {"1", "true", "yes"}
POLYMARKET_MAX_ACTIVE_MARKETS = int(os.getenv("POLYMARKET_MAX_ACTIVE_MARKETS", "60"))
POLYMARKET_EXTERNAL_TERM_LIMIT = int(os.getenv("POLYMARKET_EXTERNAL_TERM_LIMIT", "20"))
POLYMARKET_DISCOVERY_MIN_VOLUME_24H = float(os.getenv("POLYMARKET_DISCOVERY_MIN_VOLUME_24H", "5000"))
POLYMARKET_DISCOVERY_MIN_LIQUIDITY = float(os.getenv("POLYMARKET_DISCOVERY_MIN_LIQUIDITY", "2000"))
POLYMARKET_SIGNAL_MIN_MOVE_15M = float(os.getenv("POLYMARKET_SIGNAL_MIN_MOVE_15M", "0.08"))
POLYMARKET_SIGNAL_MIN_MOVE_1H = float(os.getenv("POLYMARKET_SIGNAL_MIN_MOVE_1H", "0.12"))
POLYMARKET_SIGNAL_MIN_MOVE_6H = float(os.getenv("POLYMARKET_SIGNAL_MIN_MOVE_6H", "0.20"))
POLYMARKET_SIGNAL_MIN_MOVE_24H = float(os.getenv("POLYMARKET_SIGNAL_MIN_MOVE_24H", "0.30"))
POLYMARKET_SIGNAL_MIN_QUALITY = int(os.getenv("POLYMARKET_SIGNAL_MIN_QUALITY", "70"))
POLYMARKET_SNAPSHOT_RETENTION_DAYS = int(os.getenv("POLYMARKET_SNAPSHOT_RETENTION_DAYS", "14"))
POLYMARKET_SIGNAL_RETENTION_DAYS = int(os.getenv("POLYMARKET_SIGNAL_RETENTION_DAYS", "180"))
POLYMARKET_TELEGRAM_ENABLED = os.getenv("POLYMARKET_TELEGRAM_ENABLED", "true").lower() in {"1", "true", "yes"}
POLYMARKET_TRANSLATION_ENABLED = os.getenv("POLYMARKET_TRANSLATION_ENABLED", "true").lower() in {"1", "true", "yes"}
POLYMARKET_DIGEST_ENABLED = os.getenv("POLYMARKET_DIGEST_ENABLED", "false").lower() in {"1", "true", "yes"}
POLYMARKET_DIGEST_FORCE = os.getenv("POLYMARKET_DIGEST_FORCE", "false").lower() in {"1", "true", "yes"}
POLYMARKET_DIGEST_MAX_TOPICS = int(os.getenv("POLYMARKET_DIGEST_MAX_TOPICS", "5"))
POLYMARKET_DIGEST_MARKETS_PER_TOPIC = int(os.getenv("POLYMARKET_DIGEST_MARKETS_PER_TOPIC", "3"))
POLYMARKET_DIGEST_MIN_VOLUME_24H = float(os.getenv("POLYMARKET_DIGEST_MIN_VOLUME_24H", "1000"))
POLYMARKET_DIGEST_MIN_LIQUIDITY = float(os.getenv("POLYMARKET_DIGEST_MIN_LIQUIDITY", "2000"))
POLYMARKET_DIGEST_DEDUPE_HOURS = int(os.getenv("POLYMARKET_DIGEST_DEDUPE_HOURS", "12"))
POLYMARKET_DIGEST_MODEL = os.getenv("POLYMARKET_DIGEST_MODEL") or os.getenv("DIGEST_MODEL") or os.getenv("OPENAI_MODEL") or "gemini-3-flash-preview"
POLYMARKET_DIGEST_BASE_URL = (
    os.getenv("POLYMARKET_DIGEST_BASE_URL")
    or os.getenv("DIGEST_BASE_URL")
    or os.getenv("OPENAI_BASE_URL")
    or "https://api.openai.com/v1"
).rstrip("/")
POLYMARKET_DIGEST_API_KEY = os.getenv("POLYMARKET_DIGEST_API_KEY") or os.getenv("DIGEST_API_KEY") or os.getenv("OPENAI_API_KEY")
POLYMARKET_TRANSLATION_MODEL = os.getenv("POLYMARKET_TRANSLATION_MODEL") or os.getenv("DIGEST_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
POLYMARKET_TRANSLATION_BASE_URL = (
    os.getenv("POLYMARKET_TRANSLATION_BASE_URL")
    or os.getenv("DIGEST_BASE_URL")
    or os.getenv("OPENAI_BASE_URL")
    or "https://api.openai.com/v1"
).rstrip("/")
POLYMARKET_TRANSLATION_API_KEY = os.getenv("POLYMARKET_TRANSLATION_API_KEY") or os.getenv("DIGEST_API_KEY") or os.getenv("OPENAI_API_KEY")
POLYMARKET_TITLE_TRANSLATION_CACHE_LIMIT = int(os.getenv("POLYMARKET_TITLE_TRANSLATION_CACHE_LIMIT", "300"))
DYNAMIC_WATCH_TERMS_KEY = "dynamic_watch_terms"
TITLE_TRANSLATIONS_STATE_KEY = "polymarket_title_translations"
POLYMARKET_DIGEST_STATE_KEY = "polymarket_digest_last_sent_at"
T = TypeVar("T")

STATIC_DISCOVERY_KEYWORDS = [
    "fed", "fomc", "rate cut", "interest rates", "powell", "fed chair", "kevin hassett", "scott bessent",
    "trump", "tariff", "china", "taiwan", "sanctions", "export controls", "trade war",
    "iran", "israel", "ceasefire", "hormuz", "oil", "ukraine", "russia", "nato",
    "bitcoin", "ethereum", "crypto", "sec", "etf", "stablecoin", "coinbase",
    "nvidia", "tesla", "openai", "xai", "ai", "semiconductor", "jensen huang", "vera rubin", "blackwell",
]

NOISE_RE = re.compile(r"\b(nba|nfl|mlb|nhl|ufc|soccer|football|oscars|grammy|taylor swift|movie|album|celebrity|weather)\b", re.I)
INVESTING_RE = re.compile(r"\b(fed|fomc|rate|inflation|cpi|pce|tariff|trump|china|taiwan|iran|israel|oil|hormuz|bitcoin|crypto|sec|etf|nvidia|tesla|openai|xai|ai|semiconductor|election|president|sanction|export control|recession|treasury|dollar|war|ceasefire)\b", re.I)
MEME_RE = re.compile(r"\b(gta|rihanna|carti|jesus|celebrity|album|movie)\b", re.I)
WINDOWS = [
    ("15m_shock", 15, POLYMARKET_SIGNAL_MIN_MOVE_15M),
    ("1h_shock", 60, POLYMARKET_SIGNAL_MIN_MOVE_1H),
    ("6h_shock", 360, POLYMARKET_SIGNAL_MIN_MOVE_6H),
    ("24h_shock", 1440, POLYMARKET_SIGNAL_MIN_MOVE_24H),
]
TOPIC_RULES = [
    ("Rates / Fed", re.compile(r"\b(fed|fomc|rate|interest|powell|inflation|cpi|pce|jobs|recession|treasury)\b", re.I)),
    ("Iran / Israel / Oil", re.compile(r"\b(iran|israel|ceasefire|hormuz|oil|hezbollah|uranium|enrichment|airspace|war)\b", re.I)),
    ("China / Taiwan / Policy", re.compile(r"\b(china|taiwan|tariff|sanction|export control|trump|president|election)\b", re.I)),
    ("Crypto", re.compile(r"\b(bitcoin|btc|ethereum|eth|crypto|sec|etf|coinbase|stablecoin)\b", re.I)),
    ("AI / Tech", re.compile(r"\b(nvidia|nvda|tesla|tsla|openai|xai|ai|semiconductor|jensen|robotaxi|deepseek|microsoft|mistral)\b", re.I)),
    ("Other Market Risks", INVESTING_RE),
]


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def get_supabase() -> Client:
    return create_client(require_env("SUPABASE_URL"), require_env("SUPABASE_KEY"))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def execute_with_retry(label: str, operation: Callable[[], T], retries: int = 2, delay_seconds: float = 0.6) -> T:
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break
            sleep_for = delay_seconds * (2 ** attempt)
            logger.warning("%s failed attempt=%s retrying_in=%.1fs error=%s", label, attempt + 1, sleep_for, exc)
            time.sleep(sleep_for)
    assert last_error is not None
    raise last_error


def parse_number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def first(data: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def gamma_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    response = requests.get(f"{GAMMA_BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def extract_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("markets", "events", "data", "results"):
            if isinstance(payload.get(key), list):
                return [item for item in payload[key] if isinstance(item, dict)]
        if "id" in payload or "question" in payload:
            return [payload]
    return []


def event_to_markets(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    markets = item.get("markets")
    if not isinstance(markets, list):
        return [item]
    output = []
    for market in markets:
        if isinstance(market, dict):
            row = dict(market)
            row.setdefault("event_id", item.get("id"))
            row.setdefault("eventSlug", item.get("slug"))
            row.setdefault("category", item.get("category"))
            row.setdefault("tags", item.get("tags"))
            output.append(row)
    return output


def parse_prices(value: Any) -> Tuple[Optional[float], Optional[float]]:
    parsed = parse_jsonish(value)
    if isinstance(parsed, list) and parsed:
        yes = parse_number(parsed[0])
        no = parse_number(parsed[1]) if len(parsed) > 1 else (1 - yes if yes is not None else None)
        return yes, no
    return None, None


def normalize_tags(value: Any) -> List[str]:
    parsed = parse_jsonish(value)
    tags: List[str] = []
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, str):
                tags.append(item)
            elif isinstance(item, dict):
                label = first(item, "label", "name", "slug")
                if label:
                    tags.append(str(label))
    elif isinstance(parsed, str):
        tags.append(parsed)
    return sorted({tag.strip() for tag in tags if tag and tag.strip()})[:20]


def market_url(slug: Optional[str], event_slug: Optional[str]) -> str:
    slug_value = event_slug or slug
    return f"{POLYMARKET_BASE_URL}/event/{slug_value}" if slug_value else POLYMARKET_BASE_URL


def normalize_market(raw: Dict[str, Any], source: str, base_score: int = 0) -> Optional[Dict[str, Any]]:
    market_id = str(first(raw, "id", "market_id", "marketId") or "")
    condition_id = str(first(raw, "conditionId", "condition_id") or market_id or "")
    question = str(first(raw, "question", "title", "name") or "").strip()
    if not (market_id or condition_id) or not question:
        return None

    yes_price, no_price = parse_prices(first(raw, "outcomePrices", "outcome_prices"))
    if yes_price is None:
        yes_price = parse_number(first(raw, "yesPrice", "lastTradePrice", "bestAsk", "midpoint"))
    if no_price is None and yes_price is not None:
        no_price = 1 - yes_price

    volume_24hr = parse_number(first(raw, "volume24hr", "volume24Hr", "volume_24hr", "oneDayVolume"))
    volume = parse_number(first(raw, "volume", "volumeNum", "totalVolume"))
    liquidity = parse_number(first(raw, "liquidity", "liquidityNum"))
    spread = parse_number(first(raw, "spread", "spreadNum"))
    best_bid = parse_number(first(raw, "bestBid", "best_bid"))
    best_ask = parse_number(first(raw, "bestAsk", "best_ask"))
    if spread is None and best_bid is not None and best_ask is not None:
        spread = max(best_ask - best_bid, 0)

    tags = normalize_tags(first(raw, "tags"))
    category = first(raw, "category", "categorySlug", "groupItemTitle")
    text = " ".join([question, str(category or ""), " ".join(tags)])
    if NOISE_RE.search(text):
        return None

    relevance = 30 if INVESTING_RE.search(text) else 0
    liquidity_score = int(min(math.log10(max(liquidity or 0, 1)) * 8, 30))
    volume_score = int(min(math.log10(max(volume_24hr or volume or 0, 1)) * 8, 30))
    slug = str(first(raw, "slug") or "") or None
    event_slug = str(first(raw, "eventSlug", "event_slug") or "") or None

    return {
        "market_id": market_id or condition_id,
        "condition_id": condition_id or None,
        "event_id": str(first(raw, "event_id", "eventId") or "") or None,
        "slug": slug,
        "question": question,
        "category": str(category) if category else None,
        "tags": tags,
        "source": source,
        "active": bool(first(raw, "active") if first(raw, "active") is not None else True),
        "closed": bool(first(raw, "closed") if first(raw, "closed") is not None else False),
        "end_date": first(raw, "endDate", "end_date", "endDateIso"),
        "min_volume": volume,
        "min_liquidity": liquidity,
        "watch_priority": 0,
        "discovery_score": base_score + relevance + liquidity_score + volume_score,
        "last_discovered_at": utcnow().isoformat(),
        "source_url": market_url(slug, event_slug),
        "yes_price": yes_price,
        "no_price": no_price,
        "volume": volume,
        "volume_24hr": volume_24hr,
        "liquidity": liquidity,
        "spread": spread,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "open_interest": parse_number(first(raw, "openInterest", "open_interest")),
    }


def eligible(market: Dict[str, Any]) -> bool:
    if not market.get("active") or market.get("closed"):
        return False
    volume_24hr = float(market.get("volume_24hr") or market.get("volume") or 0)
    liquidity = float(market.get("liquidity") or market.get("min_liquidity") or 0)
    return volume_24hr >= POLYMARKET_DISCOVERY_MIN_VOLUME_24H or liquidity >= POLYMARKET_DISCOVERY_MIN_LIQUIDITY


def fetch_top_markets() -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for path, params in [
        ("/events", {"active": "true", "closed": "false", "order": "volume24hr", "ascending": "false", "limit": 100}),
        ("/markets", {"active": "true", "closed": "false", "order": "volume24hr", "ascending": "false", "limit": 100}),
    ]:
        try:
            for item in extract_items(gamma_get(path, params)):
                for raw in event_to_markets(item):
                    market = normalize_market(raw, "auto_api_top", 8)
                    if market:
                        candidates.append(market)
        except Exception:
            logger.warning("Top discovery failed path=%s", path, exc_info=True)
    return candidates


def search_markets(term: str, source: str, base_score: int) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for path, params in [
        ("/public-search", {"q": term, "limit_per_type": 10}),
        ("/markets", {"active": "true", "closed": "false", "search": term, "limit": 10}),
    ]:
        try:
            for item in extract_items(gamma_get(path, params)):
                for raw in event_to_markets(item):
                    market = normalize_market(raw, source, base_score)
                    if market:
                        candidates.append(market)
        except Exception:
            logger.debug("Search failed term=%s path=%s", term, path, exc_info=True)
    return candidates


def state_value(supabase: Client, key: str) -> Optional[str]:
    response = supabase.table("system_states").select("value").eq("key", key).limit(1).execute()
    rows = response.data or []
    return str(rows[0]["value"]) if rows else None


def save_state_value(supabase: Client, key: str, value: str) -> None:
    supabase.table("system_states").upsert({"key": key, "value": value}, on_conflict="key").execute()


def chat_completions_url(base_url: str) -> str:
    cleaned = base_url.rstrip("/")
    return cleaned if cleaned.endswith("/chat/completions") else f"{cleaned}/chat/completions"


def load_title_translation_cache(supabase: Client) -> Dict[str, Any]:
    try:
        data = json.loads(state_value(supabase, TITLE_TRANSLATIONS_STATE_KEY) or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("Cannot read Polymarket title translation cache", exc_info=True)
        return {}


def save_title_translation_cache(supabase: Client, cache: Dict[str, Any]) -> None:
    try:
        items = list(cache.items())[-POLYMARKET_TITLE_TRANSLATION_CACHE_LIMIT:]
        save_state_value(supabase, TITLE_TRANSLATIONS_STATE_KEY, json.dumps(dict(items), ensure_ascii=False))
    except Exception:
        logger.warning("Cannot save Polymarket title translation cache", exc_info=True)


def translate_question_zh(supabase: Client, question: str) -> Optional[str]:
    question = question.strip()
    if not question or not POLYMARKET_TRANSLATION_ENABLED:
        return None
    cache = load_title_translation_cache(supabase)
    cached = cache.get(question)
    if isinstance(cached, dict) and cached.get("zh"):
        return str(cached["zh"])
    if not POLYMARKET_TRANSLATION_API_KEY:
        logger.info("Polymarket title translation skipped: missing API key")
        return None

    try:
        response = requests.post(
            chat_completions_url(POLYMARKET_TRANSLATION_BASE_URL),
            headers={
                "Authorization": f"Bearer {POLYMARKET_TRANSLATION_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": POLYMARKET_TRANSLATION_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "Translate Polymarket prediction-market titles into concise Traditional Chinese for Hong Kong investors. Preserve names, tickers, dates, numbers and odds context. Output only the Chinese translation.",
                    },
                    {"role": "user", "content": question},
                ],
                "temperature": 0.1,
                "max_tokens": 120,
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        translated = str(payload["choices"][0]["message"]["content"]).strip().strip('"')
        if not translated:
            return None
        cache[question] = {"zh": translated, "model": POLYMARKET_TRANSLATION_MODEL, "updated_at": utcnow().isoformat()}
        save_title_translation_cache(supabase, cache)
        return translated
    except Exception:
        logger.warning("Polymarket title translation failed model=%s", POLYMARKET_TRANSLATION_MODEL, exc_info=True)
        return None


def dynamic_terms(supabase: Client) -> List[str]:
    if not POLYMARKET_EXTERNAL_DISCOVERY_ENABLED:
        return []
    terms: List[Tuple[int, str]] = []
    try:
        data = json.loads(state_value(supabase, DYNAMIC_WATCH_TERMS_KEY) or "{}")
        if isinstance(data, dict):
            for entry in data.values():
                if isinstance(entry, dict) and entry.get("term"):
                    terms.append((int(entry.get("score") or 0), str(entry["term"])))
    except Exception:
        logger.warning("Cannot read dynamic_watch_terms", exc_info=True)

    try:
        cutoff = (utcnow() - timedelta(hours=24)).isoformat()
        response = (
            supabase.table("event_clusters")
            .select("title,tickers,sectors,impact_max,confidence_max,last_seen_at")
            .gte("last_seen_at", cutoff)
            .gte("impact_max", 7)
            .order("impact_max", desc=True)
            .limit(40)
            .execute()
        )
        for row in response.data or []:
            score = int(row.get("impact_max") or 0) * 3 + int(row.get("confidence_max") or 0)
            for value in [row.get("title"), *(row.get("tickers") or []), *(row.get("sectors") or [])]:
                term = str(value or "").strip(" $@#")
                if 2 < len(term) <= 60:
                    terms.append((score, term))
    except Exception:
        logger.warning("Cannot read event_clusters for discovery", exc_info=True)

    seen: set[str] = set()
    output: List[str] = []
    for _score, term in sorted(terms, reverse=True):
        key = term.lower()
        if key not in seen and not NOISE_RE.search(term):
            seen.add(key)
            output.append(term)
        if len(output) >= POLYMARKET_EXTERNAL_TERM_LIMIT:
            break
    return output


def discover_markets(supabase: Client) -> Dict[str, Dict[str, Any]]:
    if not POLYMARKET_DISCOVERY_ENABLED:
        return {}
    candidates: Dict[str, Dict[str, Any]] = {}
    for market in fetch_top_markets():
        if eligible(market):
            candidates[market["market_id"]] = market
    for term in STATIC_DISCOVERY_KEYWORDS + dynamic_terms(supabase):
        source = "auto_external_term" if term not in STATIC_DISCOVERY_KEYWORDS else "auto_keyword"
        base_score = 24 if source == "auto_external_term" else 16
        for market in search_markets(term, source, base_score):
            if eligible(market):
                old = candidates.get(market["market_id"])
                if not old or market["discovery_score"] > old["discovery_score"]:
                    candidates[market["market_id"]] = market

    selected = sorted(candidates.values(), key=lambda x: (x.get("discovery_score") or 0, x.get("volume_24hr") or x.get("volume") or 0), reverse=True)[:POLYMARKET_MAX_ACTIVE_MARKETS]
    rows = []
    now_iso = utcnow().isoformat()
    for item in selected:
        rows.append({
            "market_id": item["market_id"],
            "condition_id": item.get("condition_id"),
            "event_id": item.get("event_id"),
            "slug": item.get("slug"),
            "question": item["question"],
            "category": item.get("category"),
            "tags": item.get("tags") or [],
            "source": item.get("source") or "auto_discovery",
            "active": item.get("active", True),
            "closed": item.get("closed", False),
            "end_date": item.get("end_date"),
            "min_volume": item.get("volume"),
            "min_liquidity": item.get("liquidity"),
            "discovery_score": item.get("discovery_score") or 0,
            "source_url": item.get("source_url"),
            "last_discovered_at": now_iso,
            "updated_at": now_iso,
        })
    if rows:
        supabase.table("polymarket_markets").upsert(rows, on_conflict="market_id").execute()
    logger.info("Discovered %s Polymarket markets", len(rows))
    return {item["market_id"]: item for item in selected}


def active_markets(supabase: Client) -> List[Dict[str, Any]]:
    response = execute_with_retry(
        "active_markets",
        lambda: (
            supabase.table("polymarket_markets")
            .select("market_id,condition_id,slug,question,category,tags,source_url,watch_priority,discovery_score,end_date")
            .eq("active", True)
            .eq("closed", False)
            .order("watch_priority", desc=True)
            .order("discovery_score", desc=True)
            .limit(POLYMARKET_MAX_ACTIVE_MARKETS)
            .execute()
        ),
    )
    return list(response.data or [])


def fetch_market_by_id(market_id: str) -> Optional[Dict[str, Any]]:
    try:
        items = extract_items(gamma_get(f"/markets/{market_id}"))
        return normalize_market(items[0], "active_refresh", 0) if items else None
    except Exception:
        logger.debug("Market refresh failed market_id=%s", market_id, exc_info=True)
        return None


def snapshot_row(market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if market.get("yes_price") is None:
        return None
    return {
        "market_id": market["market_id"],
        "condition_id": market.get("condition_id"),
        "yes_price": market.get("yes_price"),
        "no_price": market.get("no_price"),
        "volume": market.get("volume"),
        "volume_24hr": market.get("volume_24hr"),
        "liquidity": market.get("liquidity"),
        "spread": market.get("spread"),
        "best_bid": market.get("best_bid"),
        "best_ask": market.get("best_ask"),
        "open_interest": market.get("open_interest"),
        "snapshot_at": utcnow().isoformat(),
    }


def collect_snapshots(supabase: Client, discovered: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    snapshots = []
    updates = []
    now_iso = utcnow().isoformat()
    for row in active_markets(supabase):
        market = discovered.get(str(row["market_id"])) or fetch_market_by_id(str(row["market_id"]))
        if not market:
            continue
        snapshot = snapshot_row(market)
        if not snapshot:
            continue
        snapshots.append(snapshot)
        updates.append({"market_id": row["market_id"], "last_snapshot_at": now_iso, "updated_at": now_iso})
    if snapshots:
        execute_with_retry("insert_polymarket_snapshots", lambda: supabase.table("polymarket_snapshots").insert(snapshots).execute())
    for update in updates:
        execute_with_retry(
            f"update_polymarket_market_{update['market_id']}",
            lambda update=update: supabase.table("polymarket_markets").update({
                "last_snapshot_at": update["last_snapshot_at"],
                "updated_at": update["updated_at"],
            }).eq("market_id", update["market_id"]).execute(),
        )
    logger.info("Inserted %s Polymarket snapshots", len(snapshots))
    return snapshots


def previous_snapshot(supabase: Client, market_id: str, before: datetime) -> Optional[Dict[str, Any]]:
    response = execute_with_retry(
        f"previous_snapshot_{market_id}",
        lambda: (
            supabase.table("polymarket_snapshots")
            .select("market_id,yes_price,volume,volume_24hr,liquidity,spread,snapshot_at")
            .eq("market_id", market_id)
            .lte("snapshot_at", before.isoformat())
            .order("snapshot_at", desc=True)
            .limit(1)
            .execute()
        ),
    )
    rows = response.data or []
    return rows[0] if rows else None


def quality_score(snapshot: Dict[str, Any], move: float, window_minutes: int, question: str) -> int:
    score = 30 if window_minutes <= 60 and abs(move) >= 0.12 else 22 if abs(move) >= 0.08 else 12
    volume_24hr = float(snapshot.get("volume_24hr") or snapshot.get("volume") or 0)
    liquidity = float(snapshot.get("liquidity") or 0)
    spread = snapshot.get("spread")
    if volume_24hr >= 100000:
        score += 25
    elif volume_24hr >= 50000:
        score += 20
    elif volume_24hr >= 10000:
        score += 12
    if liquidity >= 25000:
        score += 25
    elif liquidity >= 10000:
        score += 20
    elif liquidity >= 2000:
        score += 10
    if spread is not None:
        spread_value = float(spread)
        if spread_value <= 0.03:
            score += 10
        elif spread_value <= 0.08:
            score += 5
        elif spread_value > 0.12:
            score -= 20
    if INVESTING_RE.search(question):
        score += 10
    if liquidity < 2000:
        score -= 20
    return max(0, min(score, 100))


def trading_lens(question: str) -> str:
    text = question.lower()
    if any(x in text for x in ["fed", "rate", "inflation", "cpi", "pce"]):
        return "觀察 TLT、QQQ、DXY、黃金及美債收益率，確認是否與利率預期同步。"
    if any(x in text for x in ["trump", "tariff", "china", "taiwan", "sanction"]):
        return "觀察半導體、工業、美元、人民幣及政策敏感板塊。"
    if any(x in text for x in ["iran", "israel", "oil", "hormuz", "ukraine", "russia"]):
        return "觀察原油、能源股、航空、航運、黃金及避險資產。"
    if any(x in text for x in ["bitcoin", "crypto", "ethereum", "sec", "etf"]):
        return "觀察 BTC、ETH、COIN、MSTR、礦股及風險資產 beta。"
    if any(x in text for x in ["nvidia", "tesla", "openai", "ai", "semiconductor"]):
        return "觀察 NVDA、TSLA、MSFT、GOOGL、AVGO、AMD、TSM、AI 基建鏈。"
    return "觀察相關板塊是否有成交量、期權 IV 或新聞流同步確認。"


def detect_signals(supabase: Client, snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not snapshots:
        return []
    markets = {row["market_id"]: row for row in active_markets(supabase)}
    now = utcnow()
    signals = []
    for snapshot in snapshots:
        market_id = str(snapshot["market_id"])
        question = str(markets.get(market_id, {}).get("question") or market_id)
        source_url = markets.get(market_id, {}).get("source_url") or POLYMARKET_BASE_URL
        current_prob = float(snapshot["yes_price"])
        for signal_type, minutes, threshold in WINDOWS:
            previous = previous_snapshot(supabase, market_id, now - timedelta(minutes=minutes))
            if not previous or previous.get("yes_price") is None:
                continue
            old_prob = float(previous["yes_price"])
            move = current_prob - old_prob
            if abs(move) < threshold:
                continue
            qscore = quality_score(snapshot, move, minutes, question)
            if qscore < POLYMARKET_SIGNAL_MIN_QUALITY and not (abs(move) >= 0.20 and float(snapshot.get("liquidity") or 0) >= 2000):
                continue
            bucket = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0).isoformat()
            direction = "上升" if move > 0 else "下跌"
            question_zh = translate_question_zh(supabase, question)
            if question_zh:
                try:
                    supabase.table("polymarket_markets").update({"question_zh": question_zh, "updated_at": now.isoformat()}).eq("market_id", market_id).execute()
                except Exception:
                    logger.debug("Cannot update Polymarket market translation market_id=%s", market_id, exc_info=True)
            signals.append({
                "signal_key": f"{market_id}:{signal_type}:{bucket}:{round(current_prob, 3)}",
                "market_id": market_id,
                "question": question,
                "question_zh": question_zh,
                "signal_type": signal_type,
                "old_probability": round(old_prob, 4),
                "new_probability": round(current_prob, 4),
                "probability_change": round(move, 4),
                "window_minutes": minutes,
                "volume": snapshot.get("volume"),
                "volume_24hr": snapshot.get("volume_24hr"),
                "liquidity": snapshot.get("liquidity"),
                "spread": snapshot.get("spread"),
                "quality_score": qscore,
                "market_implication_zh": f"市場對「{question}」的隱含機率在 {signal_type.replace('_shock', '')} 內由 {old_prob:.0%} {direction}至 {current_prob:.0%}，代表資金正在重新定價相關風險。",
                "trading_lens_zh": trading_lens(question),
                "source_url": source_url,
                "sent_to_telegram": False,
                "created_at": now.isoformat(),
            })
    inserted = []
    for signal in signals:
        try:
            response = supabase.table("polymarket_signals").upsert(signal, on_conflict="signal_key").execute()
            inserted.extend(response.data or [signal])
        except Exception as exc:
            if "question_zh" in str(exc):
                legacy_signal = dict(signal)
                legacy_signal.pop("question_zh", None)
                try:
                    response = supabase.table("polymarket_signals").upsert(legacy_signal, on_conflict="signal_key").execute()
                    inserted.extend(response.data or [signal])
                    continue
                except Exception:
                    pass
            logger.warning("Signal insert failed market_id=%s", signal.get("market_id"), exc_info=True)
    logger.info("Detected %s Polymarket signals", len(inserted))
    return inserted


def send_telegram(message: str) -> None:
    if not POLYMARKET_TELEGRAM_ENABLED:
        return
    response = requests.post(
        f"https://api.telegram.org/bot{require_env('TELEGRAM_BOT_TOKEN')}/sendMessage",
        json={"chat_id": require_env("TELEGRAM_CHAT_ID"), "text": message, "parse_mode": "HTML", "disable_web_page_preview": False},
        timeout=15,
    )
    response.raise_for_status()


def send_telegram_chunked(message: str, max_chars: int = 3800) -> int:
    if len(message) <= max_chars:
        send_telegram(message)
        return 1
    chunks: List[str] = []
    current = ""
    for block in message.split("\n\n"):
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = block
    if current:
        chunks.append(current)
    for index, chunk in enumerate(chunks, start=1):
        suffix = f"\n\nPart {index}/{len(chunks)}" if len(chunks) > 1 else ""
        send_telegram(f"{chunk}{suffix}")
    return len(chunks)


def signal_message(signal: Dict[str, Any]) -> str:
    old_p = float(signal.get("old_probability") or 0)
    new_p = float(signal.get("new_probability") or 0)
    move = float(signal.get("probability_change") or 0)
    arrow = "▲" if move > 0 else "▼"
    question = html.escape(str(signal.get("question") or ""))
    question_zh = html.escape(str(signal.get("question_zh") or ""))
    market_lines = ["<b>Market</b>：", f"EN：{question}"]
    if question_zh:
        market_lines.append(question_zh)

    return "\n".join([
        "■■■■■■■■■■■■■■■■",
        "<b>POLYMARKET SIGNAL | PROBABILITY SHOCK</b>",
        "■■■■■■■■■■■■■■■■",
        "",
        "\n".join(market_lines),
        f"<b>Move</b>：{old_p:.0%} → {new_p:.0%} ({arrow}{abs(move):.0%}, {html.escape(str(signal.get('signal_type') or ''))})",
        f"<b>Quality</b>：{signal.get('quality_score')}/100",
        "",
        f"<b>Why it matters</b>：\n{html.escape(str(signal.get('market_implication_zh') or ''))}",
        "",
        f"<b>Trading lens</b>：\n{html.escape(str(signal.get('trading_lens_zh') or ''))}",
        "",
        f"<a href=\"{html.escape(str(signal.get('source_url') or POLYMARKET_BASE_URL))}\">Open Polymarket</a>",
    ])


def send_signals(supabase: Client, signals: List[Dict[str, Any]]) -> int:
    sent = 0
    for signal in signals:
        if signal.get("sent_to_telegram"):
            continue
        try:
            send_telegram(signal_message(signal))
            supabase.table("polymarket_signals").update({"sent_to_telegram": True}).eq("signal_key", signal["signal_key"]).execute()
            sent += 1
        except Exception:
            logger.warning("Telegram send failed for Polymarket signal", exc_info=True)
    return sent


def parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def hkt_now() -> datetime:
    return utcnow() + timedelta(hours=8)


def pct(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def signed_pts(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value > 0 else ""
    return f"{sign}{value * 100:.1f} pts"


def compact_money(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}k"
    return f"${value:.0f}"


def topic_for_market(question: str, tags: Optional[List[str]] = None, category: Optional[str] = None) -> str:
    text = " ".join([question, category or "", " ".join(tags or [])])
    for topic, pattern in TOPIC_RULES:
        if pattern.search(text):
            return topic
    return "Other Market Risks"


def is_digest_candidate(market: Dict[str, Any], snapshot: Dict[str, Any]) -> bool:
    question = str(market.get("question") or "")
    if not question or MEME_RE.search(question):
        return False
    price = parse_number(snapshot.get("yes_price"))
    if price is None or price <= 0 or price >= 1:
        return False
    volume_24hr = float(snapshot.get("volume_24hr") or snapshot.get("volume") or 0)
    liquidity = float(snapshot.get("liquidity") or 0)
    if volume_24hr < POLYMARKET_DIGEST_MIN_VOLUME_24H and liquidity < POLYMARKET_DIGEST_MIN_LIQUIDITY:
        return False
    end_date = parse_datetime(market.get("end_date"))
    if end_date and end_date < utcnow() - timedelta(hours=12):
        return False
    return bool(INVESTING_RE.search(question))


def digest_market_score(item: Dict[str, Any]) -> float:
    snapshot = item["snapshot"]
    price = float(snapshot.get("yes_price") or 0)
    volume_24hr = float(snapshot.get("volume_24hr") or snapshot.get("volume") or 0)
    liquidity = float(snapshot.get("liquidity") or 0)
    spread = snapshot.get("spread")
    moves = [abs(float(item.get(key) or 0)) for key in ("move_1h", "move_24h", "move_7d")]
    move_score = min(max(moves) * 350, 45)
    volume_score = min(math.log10(max(volume_24hr, 1)) * 7, 35)
    liquidity_score = min(math.log10(max(liquidity, 1)) * 5, 25)
    probability_score = 8 if 0.15 <= price <= 0.85 else 4
    spread_penalty = 0
    if spread is not None and float(spread) > 0.08:
        spread_penalty = 12
    return round(move_score + volume_score + liquidity_score + probability_score - spread_penalty, 2)


def enrich_digest_items(supabase: Client, markets: Dict[str, Dict[str, Any]], snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = []
    now = utcnow()
    for snapshot in snapshots:
        market_id = str(snapshot.get("market_id") or "")
        market = markets.get(market_id)
        if not market or not is_digest_candidate(market, snapshot):
            continue
        current = parse_number(snapshot.get("yes_price"))
        if current is None:
            continue
        previous_values: Dict[str, Optional[float]] = {}
        for label, minutes in [("1h", 60), ("24h", 1440), ("7d", 10080)]:
            try:
                previous = previous_snapshot(supabase, market_id, now - timedelta(minutes=minutes))
            except Exception:
                logger.warning("Digest previous snapshot skipped market_id=%s window=%s", market_id, label, exc_info=True)
                previous = None
            old = parse_number(previous.get("yes_price")) if previous else None
            previous_values[label] = current - old if old is not None else None
        question = str(market.get("question") or "")
        item = {
            "market": market,
            "snapshot": snapshot,
            "topic": topic_for_market(question, market.get("tags"), market.get("category")),
            "move_1h": previous_values["1h"],
            "move_24h": previous_values["24h"],
            "move_7d": previous_values["7d"],
        }
        item["score"] = digest_market_score(item)
        items.append(item)
    return sorted(items, key=lambda item: item["score"], reverse=True)


def choose_digest_topics(items: List[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(item["topic"], []).append(item)
    topic_rows = []
    for topic, topic_items in grouped.items():
        selected = sorted(topic_items, key=lambda item: item["score"], reverse=True)[:POLYMARKET_DIGEST_MARKETS_PER_TOPIC]
        score = sum(float(item["score"]) for item in selected)
        topic_rows.append((score, topic, selected))
    topic_rows.sort(reverse=True, key=lambda row: row[0])
    return [(topic, selected) for _score, topic, selected in topic_rows[:POLYMARKET_DIGEST_MAX_TOPICS]]


def translate_market_for_digest(supabase: Client, market: Dict[str, Any]) -> str:
    existing = str(market.get("question_zh") or "").strip()
    if existing:
        return existing
    question = str(market.get("question") or "")
    translated = translate_question_zh(supabase, question)
    if translated:
        try:
            supabase.table("polymarket_markets").update({"question_zh": translated, "updated_at": utcnow().isoformat()}).eq("market_id", market["market_id"]).execute()
        except Exception:
            logger.debug("Cannot save digest translation market_id=%s", market.get("market_id"), exc_info=True)
        return translated
    return ""


def topic_fallback_takeaway(topic: str) -> str:
    if topic == "Rates / Fed":
        return "利率相關 odds 主要反映市場對 Fed 路徑的即時定價；若 odds 快速轉向，優先檢查美債收益率、DXY、QQQ 與 TLT 是否同步。"
    if topic == "Iran / Israel / Oil":
        return "地緣風險需要同時睇外交進展與升級尾部風險；若談判 odds 跌而軍事/油價 odds 升，應提高 risk-off 權重。"
    if topic == "China / Taiwan / Policy":
        return "政策及地緣尾部風險目前主要影響半導體、工業鏈、美元與人民幣敏感資產。"
    if topic == "Crypto":
        return "Crypto odds 可作短線風險偏好溫度計；留意 BTC beta 是否同 COIN、MSTR、礦股同步。"
    if topic == "AI / Tech":
        return "AI/Tech odds 反映市場對大型科技 catalyst 和價格區間的重新定價；重點觀察 NVDA、TSLA、QQQ 與半導體鏈。"
    return "此 topic 有足夠流動性或 odds 變化，值得放入每日監察，但需配合新聞流和相關資產價格確認。"


def synthesize_topic_takeaway(topic: str, items: List[Dict[str, Any]]) -> str:
    if not POLYMARKET_DIGEST_API_KEY:
        return topic_fallback_takeaway(topic)
    compact_items = []
    for item in items:
        market = item["market"]
        snapshot = item["snapshot"]
        compact_items.append({
            "question": market.get("question"),
            "odds": snapshot.get("yes_price"),
            "move_1h": item.get("move_1h"),
            "move_24h": item.get("move_24h"),
            "move_7d": item.get("move_7d"),
            "volume_24h": snapshot.get("volume_24hr"),
            "liquidity": snapshot.get("liquidity"),
        })
    try:
        response = requests.post(
            chat_completions_url(POLYMARKET_DIGEST_BASE_URL),
            headers={
                "Authorization": f"Bearer {POLYMARKET_DIGEST_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": POLYMARKET_DIGEST_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You write concise Traditional Chinese market brief takeaways for a Hong Kong investor. "
                            "Use the supplied odds only as market-implied probabilities. Do not invent numbers. "
                            "Return 1-2 short sentences, no bullet points, no markdown."
                        ),
                    },
                    {"role": "user", "content": json.dumps({"topic": topic, "markets": compact_items}, ensure_ascii=False)},
                ],
                "temperature": 0.2,
                "max_tokens": 180,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        text = str(payload["choices"][0]["message"]["content"]).strip()
        return text or topic_fallback_takeaway(topic)
    except Exception:
        logger.warning("Polymarket digest synthesis failed topic=%s model=%s", topic, POLYMARKET_DIGEST_MODEL, exc_info=True)
        return topic_fallback_takeaway(topic)


def digest_item_lines(supabase: Client, item: Dict[str, Any]) -> List[str]:
    market = item["market"]
    snapshot = item["snapshot"]
    question = html.escape(str(market.get("question") or ""))
    question_zh = html.escape(translate_market_for_digest(supabase, market))
    odds = pct(parse_number(snapshot.get("yes_price")))
    move_parts = []
    if item.get("move_1h") is not None:
        move_parts.append(f"1h: {signed_pts(item.get('move_1h'))}")
    if item.get("move_24h") is not None:
        move_parts.append(f"24h: {signed_pts(item.get('move_24h'))}")
    if item.get("move_7d") is not None:
        move_parts.append(f"7d: {signed_pts(item.get('move_7d'))}")
    change_text = " | ".join(move_parts[:2]) if move_parts else "change: N/A"
    volume = compact_money(parse_number(snapshot.get("volume_24hr") or snapshot.get("volume")))
    lines = [
        f"• {question}",
    ]
    if question_zh:
        lines.append(f"  {question_zh}")
    lines.append(f"  Odds: {odds}（市場隱含機率） | {change_text} | 24h vol: {volume}")
    return lines


def build_polymarket_digest_message(supabase: Client, topics: List[Tuple[str, List[Dict[str, Any]]]]) -> str:
    now_hkt = hkt_now()
    lines = [
        "■■■■■■■■■■■■■■■■",
        "<b>POLYMARKET MARKET BRIEF</b>",
        f"HKT {now_hkt:%Y-%m-%d %H:%M}",
        "■■■■■■■■■■■■■■■■",
        "",
        "Odds = 市場隱含機率，不等於客觀真實概率。",
    ]
    for index, (topic, items) in enumerate(topics, start=1):
        lines.extend(["", f"<b>{index}. {html.escape(topic)}</b>", ""])
        for item in items:
            lines.extend(digest_item_lines(supabase, item))
            lines.append("")
        lines.extend([
            "<b>Takeaway</b>:",
            html.escape(synthesize_topic_takeaway(topic, items)),
        ])
    return "\n".join(lines).strip()


def should_send_digest(supabase: Client) -> bool:
    if not POLYMARKET_DIGEST_ENABLED:
        return False
    if POLYMARKET_DIGEST_FORCE:
        return True
    try:
        last_sent = parse_datetime(state_value(supabase, POLYMARKET_DIGEST_STATE_KEY))
        return not last_sent or last_sent <= utcnow() - timedelta(hours=POLYMARKET_DIGEST_DEDUPE_HOURS)
    except Exception:
        logger.warning("Cannot read Polymarket digest state; allowing digest", exc_info=True)
        return True


def send_polymarket_digest(supabase: Client, snapshots: List[Dict[str, Any]]) -> int:
    if not should_send_digest(supabase):
        logger.info("Polymarket digest skipped by gate")
        return 0
    markets = {row["market_id"]: row for row in active_markets(supabase)}
    items = enrich_digest_items(supabase, markets, snapshots)
    topics = choose_digest_topics(items)
    if not topics:
        logger.info("Polymarket digest skipped: no qualifying topics")
        return 0
    message = build_polymarket_digest_message(supabase, topics)
    chunks = send_telegram_chunked(message)
    save_state_value(supabase, POLYMARKET_DIGEST_STATE_KEY, utcnow().isoformat())
    logger.info("Sent Polymarket digest topics=%s items=%s chunks=%s", len(topics), sum(len(topic_items) for _topic, topic_items in topics), chunks)
    return 1


def cleanup(supabase: Client) -> None:
    for table, column, days in [
        ("polymarket_snapshots", "snapshot_at", POLYMARKET_SNAPSHOT_RETENTION_DAYS),
        ("polymarket_signals", "created_at", POLYMARKET_SIGNAL_RETENTION_DAYS),
    ]:
        try:
            cutoff = (utcnow() - timedelta(days=days)).isoformat()
            response = supabase.table(table).delete().lt(column, cutoff).execute()
            logger.info("Cleanup %s deleted %s rows", table, len(response.data or []))
        except Exception:
            logger.warning("Cleanup skipped for %s", table, exc_info=True)


def main() -> int:
    if not POLYMARKET_ENABLED:
        logger.info("Polymarket monitor disabled")
        return 0
    if POLYMARKET_APIFY_FALLBACK_ENABLED:
        logger.warning("POLYMARKET_APIFY_FALLBACK_ENABLED is reserved but not used in MVP to avoid unexpected Apify cost")
    supabase = get_supabase()
    cleanup(supabase)
    discovered = discover_markets(supabase)
    snapshots = collect_snapshots(supabase, discovered)
    signals = detect_signals(supabase, snapshots)
    sent = send_signals(supabase, signals)
    digest_sent = send_polymarket_digest(supabase, snapshots)
    logger.info("Polymarket run complete discovered=%s snapshots=%s signals=%s sent=%s digest_sent=%s", len(discovered), len(snapshots), len(signals), sent, digest_sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
