# AI Scraper - Financial Intelligence Monitor

Last updated: 2026-06-15 HKT

This repository is an automated financial intelligence system. It monitors high-signal X/Twitter accounts, filters market-relevant posts with AI, stores all structured data in Supabase, sends important alerts and scheduled digests to Telegram, and exposes dashboards through a Next.js app on Vercel.

It also includes a separate Polymarket Probability Radar that tracks prediction-market probability shocks using Polymarket public APIs.

Primary user goal: reduce financial-news noise while still catching market-moving events quickly enough to act on them.

## Current Production URLs

- Dashboard: `https://ai-scraper-phi.vercel.app/`
- Study view: `https://ai-scraper-phi.vercel.app/study`
- Alerts archive: `https://ai-scraper-phi.vercel.app/alerts`
- Polymarket radar: `https://ai-scraper-phi.vercel.app/polymarket`
- GitHub repo: `jasonnkh1991/AI_Scraper`

## Architecture

```text
X/Twitter accounts
  -> Apify actor
  -> crawler.py
  -> Supabase tweet_queue
  -> AI scoring + clustering
  -> Telegram critical alerts / scheduled digests
  -> Supabase insights + event_clusters + telegram_alerts
  -> Next.js dashboard + /study

Polymarket public APIs
  -> polymarket_monitor.py
  -> Supabase polymarket_markets + polymarket_snapshots
  -> probability-shock detection
  -> Telegram Polymarket alerts
  -> /polymarket dashboard
```

The X pipeline and Polymarket pipeline are intentionally independent. If Polymarket fails, the X/Twitter monitor should still work.

## Important Files

| File | Purpose |
| --- | --- |
| `crawler.py` | Main X/Twitter automation, AI scoring, queue processing, clustering, Telegram alerts, digests, cleanup. |
| `polymarket_monitor.py` | Polymarket market discovery, snapshots, probability shock detection, Telegram alerting. |
| `.github/workflows/monitor.yml` | GitHub Actions workflow for X/Twitter monitor. Manual dispatch currently used; can be triggered externally by cron-job.org. |
| `.github/workflows/polymarket.yml` | GitHub Actions workflow for Polymarket radar, scheduled every 15 minutes. |
| `supabase/schema.sql` | Database schema for all production tables. Run relevant blocks in Supabase SQL Editor after schema changes. |
| `app/page.tsx` | Main signals dashboard. |
| `app/alerts/page.tsx` | Telegram alert archive page. |
| `app/study/page.tsx` | AI Study View, designed for copying daily cluster Markdown into another AI tool. |
| `app/study/CopyMarkdownButton.tsx` | Copy button for `/study` Markdown export. |
| `app/polymarket/page.tsx` | Polymarket dashboard. |
| `lib/supabase-server.ts` | Server-side Supabase client for Next.js pages. |
| `docs/daily-market-intelligence-skill.md` | Skill/prompt for using `/study` Markdown inside another AI tool. |
| `docs/automation-trigger-options.md` | Notes on GitHub Actions vs external cron alternatives. |
| `docs/polymarket-implementation-plan.md` | Polymarket feature plan and design notes. |

## Database Tables

Run `supabase/schema.sql` in Supabase SQL Editor when setting up or after schema updates.

Main tables:

| Table | Purpose |
| --- | --- |
| `system_states` | Key-value state store: last run state, digest date markers, dynamic terms, translation cache. |
| `tweet_queue` | Stores fetched tweets before AI processing. Prevents data loss when AI cannot process everything immediately. |
| `insights` | Stores high-value AI-evaluated tweets and structured market metadata. |
| `event_clusters` | Stores merged events/clusters so repeated tweets can be grouped. `/study` is cluster-first. |
| `telegram_alerts` | Archive of messages that were sent, or study-only alert records. |
| `daily_study_briefs` | Stores generated daily Markdown for `/study`. |
| `polymarket_markets` | Active discovered Polymarket markets. |
| `polymarket_snapshots` | Compact probability/liquidity snapshots. Default retention: 14 days. |
| `polymarket_signals` | Probability shock events. Default retention: 180 days. |

RLS is enabled with public read policies for dashboard tables. Writes are expected to use the Supabase service-role key through GitHub Secrets.

## X/Twitter Monitor

### Watchlist Design

There are two X account tiers.

Tier 1 is high priority and fetched more frequently:

```text
DeItaone
financialjuice
unusual_whales
zerohedge
WSJ
CNBC
business
Reuters
ReutersBiz
Benzinga
```

Tier 2 is lower-noise / slower cadence:

```text
elonmusk
sama
satyanadella
sundarpichai
dylan522p
IanCutress
tomshardware
StockMKTNewz
KobeissiLetter
FirstSquawk
```

Default queries live in `crawler.py` as `DEFAULT_TIER1_TWITTER_SEARCH_QUERY` and `DEFAULT_TIER2_TWITTER_SEARCH_QUERY`. They can be overridden by GitHub Secrets:

- `TIER1_TWITTER_SEARCH_QUERY`
- `TIER2_TWITTER_SEARCH_QUERY`

### Apify Actor

The X/Twitter crawler currently defaults to ScrapeBadger actor:

```text
APIFY_ACTOR_ID=pzMmk1t7AZ8OKJhfU
```

This uses Twitter advanced search queries instead of a single X List URL. It was chosen because previous list scraping was more expensive and less predictable.

### Queue Processing

The crawler does not assume every fetched tweet can be processed immediately.

Flow:

```text
fetch tweets -> enqueue tweet_queue -> priority score -> AI evaluates limited batch -> mark processed/failed/stale
```

Important env controls:

- `FETCH_LIMIT`: Tier 1 fetch limit.
- `TIER2_FETCH_LIMIT`: Tier 2 fetch limit.
- `OVERNIGHT_FETCH_LIMIT`: overnight fetch limit.
- `AI_PROCESS_LIMIT`: manual dispatch default cap.
- `PRIORITY_AI_PROCESS_LIMIT`: max high-priority queued tweets per run.
- `NORMAL_AI_PROCESS_LIMIT`: max normal queued tweets per run.
- `STALE_PENDING_HOURS`: stale queue threshold, currently 18 hours.

The system should not silently ignore fetched tweets. If AI capacity is lower than fetched volume, tweets remain pending in `tweet_queue` until processed, failed, or later marked stale by cleanup logic.

### Priority Queue

Priority is calculated in `calculate_priority()` using:

- author importance
- recency
- market keywords
- ticker/catalyst language
- dynamic watch terms
- quoted/linked information

This is a queue ordering mechanism, not a final truth filter. Important accounts like Elon Musk can still be covered, but low-market-impact posts may score lower.

### Dynamic Watch Terms

The project includes dynamic keyword learning in `crawler.py`.

Purpose: avoid blind spots when new names/themes appear, for example a new Fed chair candidate or new geopolitical term.

Relevant state key:

```text
dynamic_watch_terms
```

Relevant env:

- `DYNAMIC_WATCH_TERMS_ENABLED=true`
- `DYNAMIC_WATCH_TERM_TTL_HOURS=168`
- `DYNAMIC_WATCH_TERM_LIMIT=80`
- `DYNAMIC_WATCH_TERM_MAX_BONUS=25`
- `DYNAMIC_WATCH_TOTAL_MAX_BONUS=45`

Dynamic terms are learned from recent high-value tweets/clusters and then used as priority bonuses and Polymarket discovery terms.

### AI Evaluation Schema

For each selected tweet/group, AI outputs structured fields such as:

- `has_market_impact`
- `impact_score`
- `confidence_score`
- `target_sectors`
- `tickers`
- `summary_zh`
- `translation_zh`
- `trading_action`
- `risk_factors`
- `time_horizon`
- `source_quality`

Immediate Telegram alerts are intentionally strict:

```text
impact_score >= 8
confidence_score >= 7
```

Lower-impact but useful content should still be stored for `/study` and digests rather than spamming Telegram.

## Telegram Behavior

Telegram has two types of output.

### 1. Immediate Critical Alerts

Sent only when the event is sufficiently important and confident.

Default threshold:

```text
IMMEDIATE_ALERT_MIN_IMPACT=8
IMMEDIATE_ALERT_MIN_CONFIDENCE=7
CRITICAL_ALERT_IMPACT_SCORE=9
```

### 2. Scheduled Digests

Digests are designed to reduce information overload. They should include important processed clusters and high-priority pending queue items so digest summaries do not ignore backlog.

Current digest windows:

| HKT Time | Digest | Purpose |
| --- | --- | --- |
| 08:00 | Overnight Market Digest | Summarize overnight US-market information for Hong Kong morning. |
| 20:30 | Pre-Market Brief | Prepare before US pre-market/open. |
| 23:15 | Market Open Recap | Summarize early market-open developments. |
| 02:30 | Midday / Power Hour Prep | US midday / power-hour preparation. |

Digest model is controlled separately from normal tweet scoring:

```text
DIGEST_MODEL=gemini-3-flash-preview
DIGEST_BASE_URL=<OpenAI-compatible gateway base URL>
DIGEST_API_KEY=<optional; falls back to OPENAI_API_KEY>
```

If `DIGEST_API_KEY` is missing, `crawler.py` falls back to `OPENAI_API_KEY`.

## `/study` Page

`/study` is designed for downstream AI analysis.

It exports cluster-oriented Markdown, not raw tweet spam. The expected workflow is:

1. Open `/study`.
2. Select HKT date.
3. Click `Copy Markdown`.
4. Paste into another AI tool together with `docs/daily-market-intelligence-skill.md`.
5. Ask for a daily investment study, catalyst map, watchlist, and risk review.

`/study` should not include the scheduled digest message itself. It should show underlying clusters/events so another AI can audit the source material.

## Polymarket Probability Radar

Polymarket is a separate signal layer.

Purpose:

```text
X scraper = what people/news accounts are saying
Polymarket radar = what prediction-market money is repricing
```

### Data Source

Default source is Polymarket public Gamma API. No Polymarket API key is required.

Apify fallback is intentionally disabled by default to avoid unexpected Apify cost:

```text
POLYMARKET_APIFY_FALLBACK_ENABLED=false
```

### Discovery

Polymarket discovery combines:

- top active Polymarket markets by volume/liquidity
- static investing keywords in `STATIC_DISCOVERY_KEYWORDS`
- dynamic terms learned from X/Twitter clusters
- recent high-impact `event_clusters`

Default active market cap:

```text
POLYMARKET_MAX_ACTIVE_MARKETS=60
```

### Signal Thresholds

Signals are generated only when probability moves enough and quality is high enough:

```text
15m move >= 8 percentage points
1h move >= 12 percentage points
6h move >= 20 percentage points
24h move >= 30 percentage points
quality_score >= 70
```

A run may discover and snapshot 60 markets but send only one Telegram alert. That is expected if only one market crosses the probability-shock thresholds.

### Polymarket Title Translation

Polymarket signal messages preserve the English market title and add a Traditional Chinese translation.

Translation is optional and only runs when a signal is actually sent. It uses an OpenAI-compatible chat-completions endpoint.

Priority order:

```text
POLYMARKET_TRANSLATION_API_KEY
DIGEST_API_KEY
OPENAI_API_KEY
```

Model priority:

```text
POLYMARKET_TRANSLATION_MODEL
DIGEST_MODEL
OPENAI_MODEL
gpt-4o-mini
```

Translations are cached in `system_states` key:

```text
polymarket_title_translations
```

Important: Polymarket signal detection itself is deterministic rule-based. AI is currently only used for title translation, not for deciding whether a Polymarket event matters.

## GitHub Actions

### X/Twitter Workflow

File:

```text
.github/workflows/monitor.yml
```

Current state: manual dispatch is available. External cron can call this workflow through GitHub API if GitHub schedule reliability is not good enough.

Job timeout:

```text
timeout-minutes: 10
```

### Polymarket Workflow

File:

```text
.github/workflows/polymarket.yml
```

Current schedule:

```yaml
schedule:
  - cron: "*/15 * * * *"
```

GitHub cron is best-effort and can be delayed. For better punctuality, use cron-job.org to trigger `workflow_dispatch` through GitHub API.

### Polymarket Daily Market Brief

The 15-minute Polymarket workflow continues to run probability-shock detection. Daily market briefs are opt-in and are intended to be triggered by an external cron service such as cron-job.org through `workflow_dispatch`.

Dispatch inputs:

```json
{
  "ref": "main",
  "inputs": {
    "send_digest": "true",
    "force_digest": "false"
  }
}
```

`send_digest=true` sends a dynamic Polymarket market brief after the normal radar run. `force_digest=true` bypasses the digest dedupe window and should only be used for manual testing.

Digest env controls:

```text
POLYMARKET_DIGEST_MODEL=gemini-3-flash-preview
POLYMARKET_DIGEST_MAX_TOPICS=5
POLYMARKET_DIGEST_MARKETS_PER_TOPIC=3
POLYMARKET_DIGEST_DEDUPE_HOURS=6
```

The digest ranks topics dynamically from active markets using volume, liquidity, odds moves, topic relevance, and event recency. It should not hardcode Iran/Fed/Crypto forever; if a topic goes quiet or resolves, it should naturally fall out of the brief.

## External Cron Option

For cron-job.org, use GitHub workflow dispatch API.

Example curl for Polymarket:

```bash
curl -X POST \
  https://api.github.com/repos/jasonnkh1991/AI_Scraper/actions/workflows/polymarket.yml/dispatches \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer YOUR_GITHUB_TOKEN_HERE" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -H "Content-Type: application/json" \
  -d '{"ref":"main"}'
```

GitHub returns `204 No Content` for successful dispatch. Configure cron-job.org to treat 2xx/204 as success.

For the X monitor, replace `polymarket.yml` with `monitor.yml`. If inputs are needed, send them in JSON body.

## Required GitHub Secrets

Core secrets:

```text
SUPABASE_URL
SUPABASE_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
OPENAI_API_KEY
OPENAI_BASE_URL
OPENAI_MODEL
APIFY_TOKEN
```

Optional/fallback secrets:

```text
DIGEST_API_KEY
DIGEST_BASE_URL
DIGEST_MODEL
TIER1_TWITTER_SEARCH_QUERY
TIER2_TWITTER_SEARCH_QUERY
TWITTER_LIST_URL
```

Current digest recommendation:

```text
DIGEST_MODEL=gemini-3-flash-preview
```

If `DIGEST_API_KEY` is not set, the system uses `OPENAI_API_KEY`.

## Required Vercel Environment Variables

For dashboard pages:

```text
SUPABASE_URL
SUPABASE_KEY
```

After changing Vercel env vars, redeploy the project.

## Cost Controls

Main cost sources:

1. Apify X/Twitter scraping.
2. AI model calls for tweet scoring and digest synthesis.
3. Polymarket public API is free by default.
4. Supabase storage if retention is too long.

Current retention controls:

```text
QUEUE_PROCESSED_RETENTION_DAYS=7
QUEUE_STALE_RETENTION_DAYS=3
QUEUE_FAILED_RETENTION_DAYS=14
INSIGHTS_RETENTION_DAYS=90
CLUSTERS_RETENTION_DAYS=180
TELEGRAM_ALERTS_RETENTION_DAYS=180
DAILY_BRIEFS_RETENTION_DAYS=365
POLYMARKET_SNAPSHOT_RETENTION_DAYS=14
POLYMARKET_SIGNAL_RETENTION_DAYS=180
```

Do not increase fetch limits without checking Apify spend. If Telegram becomes too noisy, raise immediate alert thresholds and rely more on scheduled digests.

## Local Development

Install dependencies:

```bash
npm install
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Run dashboard:

```bash
npm run dev
```

Run X crawler locally:

```bash
python crawler.py
```

Run Polymarket locally:

```bash
python polymarket_monitor.py
```

Run tests:

```bash
python3 -m unittest tests.test_polymarket_monitor tests.test_market_window tests.test_alert_grouping tests.test_apify_payload tests.test_truth_social
npm run lint
npm run build
```

## Common Debugging

### GitHub workflow says no new tweets

Possible causes:

- Apify actor returned no items.
- Fetched tweets are older than `last_processed_tweet_id` / already in queue.
- Tweets were queued but not AI-processed yet because of process limits.
- Current market window logic skipped expensive work.

Check GitHub Actions logs for lines like:

```text
Fetching X Tier 1 limit=...
Queued ... tweets
Processing priority queue...
```

### Telegram gets too many messages

Use these controls:

- Raise `IMMEDIATE_ALERT_MIN_IMPACT`.
- Raise `IMMEDIATE_ALERT_MIN_CONFIDENCE`.
- Reduce `MAX_DIGEST_EVENTS` only if digests are too long.
- Keep lower-impact events in `/study` instead of Telegram.

### Pending queue grows

This means fetching is faster than AI processing.

Options:

- Increase `PRIORITY_AI_PROCESS_LIMIT` carefully.
- Reduce fetch limits.
- Improve priority scoring.
- Ensure scheduled digests include high-priority pending rows.
- Avoid deleting pending data too aggressively unless storage/cost requires it.

### Polymarket sends only one alert

Expected if only one market crosses shock thresholds. Check logs for:

```text
discovered=60 snapshots=60 signals=1 sent=1
```

This means 60 markets were watched, but only one had a qualifying probability shock.

### Supabase SQL error near comma/semicolon

Usually caused by running an interrupted or duplicated schema block. Prefer running the full current `supabase/schema.sql`, or run small `alter table ... add column if not exists ...` patches provided by the agent.

## Current Design Principles

- Store more than you send.
- Telegram should be actionable, not exhaustive.
- `/study` should preserve enough context for deep daily analysis.
- AI should not be forced to process every tweet immediately if queueing can preserve data.
- Digests must include high-priority pending items so backlog does not hide important events.
- Polymarket should remain additive and low-cost unless explicitly upgraded.
- Use deterministic filters for cheap triage; use stronger models only for synthesis/digest when needed.

## Notes For Future AI Agents

Before editing code:

1. Read this README.
2. Check `git status --short`.
3. Read the relevant file before changing it.
4. Do not revert user changes.
5. Keep X/Twitter and Polymarket pipelines independent.
6. Run focused tests plus `npm run build` after frontend/schema-related changes.
7. If changing database columns, update both `supabase/schema.sql` and relevant dashboard selects/types.
8. If changing Telegram format, consider `/study` archive implications.
9. If changing queue limits, discuss cost/noise tradeoff.
10. If changing workflow schedules, remember GitHub cron is not punctual; external cron may be preferred.
