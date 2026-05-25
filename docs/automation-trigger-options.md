# Automation Trigger Options

Current production trigger: GitHub Actions scheduled workflow.

## Current Setup

- GitHub Actions wakes every 15 minutes with `cron: "*/15 * * * *"`.
- `crawler.py` decides whether to actually call Apify/OpenAI using New York time.
- Active windows:
  - NY 06:00-20:00: run every 15 minutes.
  - NY 20:00-24:00: run only at minute 00 and 30.
  - NY 00:00-06:00: skip without calling Apify/OpenAI.
- `FETCH_LIMIT=5`.

## Alternative Trigger Options

### Vercel Cron Jobs

Good fit if the crawler is moved into a Next.js API route or if a route triggers a worker.

Pros:
- Same platform as the dashboard.
- Simple deployment and environment variable management.

Cons:
- Hobby/free cron frequency can be limited.
- Python crawler may need to be rewritten or wrapped.

### Supabase Scheduled Edge Functions

Good fit if the automation is rewritten in TypeScript/Deno and kept close to the database.

Pros:
- Clean integration with Supabase secrets and database writes.
- More backend-like than GitHub Actions.

Cons:
- Requires rewriting the crawler from Python.
- Need to monitor Supabase function limits.

### Apify Schedule

Good fit if Apify becomes the main orchestration layer.

Pros:
- Native scheduling for scraping.
- Directly tied to actor runs.

Cons:
- Still needs post-processing for OpenAI, Telegram, and Supabase.
- Webhook architecture becomes more complex.
- Does not reduce Apify usage cost by itself.

### External Cron Service

Examples: cron-job.org, EasyCron, UptimeRobot.

Pros:
- Simple scheduled HTTP calls.
- Can call a protected Vercel `/api/cron` endpoint.

Cons:
- Requires a public endpoint with a secret token.
- Reliability depends on the provider.

### Self-Hosted Cron

Examples: Mac mini, NAS, VPS.

Pros:
- Most control over schedule and logs.
- No GitHub schedule delay.

Cons:
- Machine must stay online.
- Secrets, logging, and monitoring are self-managed.

### Cloudflare Workers Cron Triggers

Good fit for a lightweight trigger or orchestration layer.

Pros:
- Large free tier.
- Stable cron triggers.
- Fast and globally distributed.

Cons:
- Python crawler cannot run directly.
- Would need JS/TS rewrite or an HTTP endpoint to call.

## Current Recommendation

Keep GitHub Actions for now. It is free, simple, works with the existing Python crawler, and keeps secrets out of the public repo.

If GitHub schedule delay becomes unacceptable, the next best option is an external cron service calling a protected Vercel API route, or a self-hosted cron if a long-running machine is available.
