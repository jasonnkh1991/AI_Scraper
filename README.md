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
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TWITTER_LIST_URL`

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
