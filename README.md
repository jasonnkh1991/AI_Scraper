# AI Financial Insight Monitor

X List -> Apify -> OpenAI filter -> Telegram alert -> Supabase -> Next.js dashboard.

## 1. Supabase

Run `supabase/schema.sql` in Supabase SQL Editor.

Use the service-role key for GitHub Actions. For the dashboard, a server-only key is fine because it is never exposed to the browser.

## 2. GitHub Secrets

Add these repository secrets:

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `APIFY_TOKEN`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TWITTER_LIST_URL` optional for the old list actor
- `TWITTER_SEARCH_QUERY` for the default low-cost ScrapeBadger actor

## 3. Vercel Environment Variables

Add:

- `SUPABASE_URL`
- `SUPABASE_KEY`

## 4. Local Dashboard

```bash
npm install
npm run dev
```

## 5. Local Crawler Test

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python crawler.py
```

## Low-Cost Apify Mode

The crawler now defaults to ScrapeBadger's `pzMmk1t7AZ8OKJhfU` actor, using Twitter Advanced Search instead of an X List URL.

Recommended query:

```text
(from:realDonaldTrump OR from:TrumpDailyPosts OR from:RNCResearch OR from:Acyn OR from:DeitaOne OR from:FinancialJuice OR from:unusual_whales OR from:dylan522p OR from:IanCutress OR from:tomshardware OR from:elonmusk OR from:samaltman OR from:satyanadella OR from:sundarpichai OR from:POTUS) -filter:replies lang:en
```

Set this in GitHub Secrets as `TWITTER_SEARCH_QUERY`.

To return to the old X List URL mode, set `APIFY_ACTOR_ID=apidojo/tweet-scraper` in the workflow and keep `TWITTER_LIST_URL`.

## Truth Social Monitoring

The crawler also monitors Donald Trump's Truth Social profile through Apify actor `IWIOv7oeNxfcjTnX5`.

Defaults:

```text
TRUTH_SOCIAL_ENABLED=true
TRUTH_SOCIAL_URL=https://www.truthsocial.com/realDonaldTrump/
TRUTH_SOCIAL_FETCH_LIMIT=3
TRUTH_SOCIAL_RUN_MINUTES=60
```

Truth Social posts are normalized into the same insight pipeline with IDs like `truth-<post_id>` and author handle `truth:realDonaldTrump`.

Cost note: this actor currently charges per actor start plus per result, so it is intentionally throttled to once per hour by default.

## Polymarket Probability Radar

This is an additive pipeline. It does not replace or modify the X/Twitter crawler.

Files:

- `polymarket_monitor.py` - pulls Polymarket public Gamma API data, discovers investment-relevant markets, stores compact snapshots, detects probability shocks, and sends Telegram alerts.
- `.github/workflows/polymarket.yml` - runs the Polymarket radar every 15 minutes.
- `/polymarket` - dashboard page for active markets and probability-shock signals.

Required setup:

1. Run the `polymarket_*` SQL blocks in `supabase/schema.sql` in Supabase SQL Editor.
2. No Polymarket API key is required.
3. Reuse existing GitHub Secrets: `SUPABASE_URL`, `SUPABASE_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
4. Run GitHub Actions workflow `Monitor Polymarket` manually once. First run may only create snapshots; signals normally require at least two snapshots to compare probability moves.

Cost controls:

- `POLYMARKET_MAX_ACTIVE_MARKETS=60`
- `POLYMARKET_SNAPSHOT_RETENTION_DAYS=14`
- `POLYMARKET_APIFY_FALLBACK_ENABLED=false`

The radar uses public Polymarket APIs by default. Apify fallback is intentionally disabled in MVP to avoid unexpected Apify spend.
