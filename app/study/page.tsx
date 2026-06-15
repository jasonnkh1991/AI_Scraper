import Link from "next/link";
import { CopyMarkdownButton } from "./CopyMarkdownButton";
import { getSupabaseServerClient } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type SearchParams = Promise<{ date?: string }>;

type EventCluster = {
  id: number;
  fingerprint: string;
  title: string;
  summary_zh: string;
  why_it_matters_zh: string | null;
  market_mechanism_zh: string | null;
  trading_action: string | null;
  risk_zh: string | null;
  impact_max: number;
  confidence_avg: number | null;
  confidence_max: number | null;
  source_quality: string | null;
  time_horizon: string | null;
  tickers: string[] | null;
  sectors: string[] | null;
  tweet_ids: string[] | null;
  source_handles: string[] | null;
  source_tweet_urls: string[] | null;
  source_count: number;
  first_seen_at: string;
  last_seen_at: string;
  last_tweet_created_at: string | null;
};

type PendingTweet = {
  tweet_id: string;
  author_handle: string;
  tweet_text: string;
  tweet_url: string;
  tweet_created_at: string | null;
  priority_score: number;
  priority_reason: string[] | null;
  inserted_at: string;
};

function hktDateString(date = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function dateBounds(date: string) {
  const start = new Date(`${date}T00:00:00+08:00`);
  const end = new Date(start.getTime() + 24 * 60 * 60 * 1000);
  return { start: start.toISOString(), end: end.toISOString() };
}

function hktTime(value: string | null) {
  if (!value) return "時間未知";
  return new Intl.DateTimeFormat("zh-HK", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Hong_Kong",
  }).format(new Date(value));
}

function periodLabel(value: string | null) {
  if (!value) return "未分類";
  const hour = Number(
    new Intl.DateTimeFormat("en-US", {
      hour: "2-digit",
      hour12: false,
      timeZone: "Asia/Hong_Kong",
    }).format(new Date(value)),
  );
  if (hour < 8) return "Overnight 00:00-08:00";
  if (hour < 12) return "Morning 08:00-12:00";
  if (hour < 16) return "Midday 12:00-16:00";
  if (hour < 20) return "US Pre-market/Open 16:00-20:00";
  return "US Market 20:00-00:00";
}

function uniq(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)));
}

function buildMarkdown(date: string, clusters: EventCluster[], pending: PendingTweet[]) {
  const lines = [
    `# Daily Market Study Brief - ${date} HKT`,
    "",
    `Event clusters: ${clusters.length}`,
    `High-priority pending: ${pending.length}`,
  ];
  const grouped = clusters.reduce<Record<string, EventCluster[]>>((acc, cluster) => {
    const label = periodLabel(cluster.last_seen_at || cluster.first_seen_at);
    acc[label] = acc[label] || [];
    acc[label].push(cluster);
    return acc;
  }, {});

  if (clusters.length === 0 && pending.length === 0) {
    lines.push("", "No event clusters or high-priority pending tweets for this date yet.");
    return lines.join("\n");
  }

  for (const [period, items] of Object.entries(grouped)) {
    lines.push("", `## ${period}`);
    for (const cluster of items) {
      const tickers = (cluster.tickers ?? []).join(", ") || "N/A";
      const sectors = (cluster.sectors ?? []).join(", ") || "N/A";
      const sources = cluster.source_tweet_urls ?? [];
      lines.push(
        "",
        `### ${cluster.title}`,
        `- Time: ${hktTime(cluster.last_seen_at)} HKT`,
        `- Impact: ${cluster.impact_max}/10`,
        `- Confidence: ${cluster.confidence_avg ?? cluster.confidence_max ?? "N/A"}/10`,
        `- Source count: ${cluster.source_count}`,
        `- Source quality: ${cluster.source_quality ?? "unknown"}`,
        `- Time horizon: ${cluster.time_horizon ?? "unclear"}`,
        `- Tickers: ${tickers}`,
        `- Sectors: ${sectors}`,
        "",
        `Summary: ${cluster.summary_zh}`,
        "",
        `Why it matters: ${cluster.why_it_matters_zh || "N/A"}`,
        "",
        `Mechanism: ${cluster.market_mechanism_zh || "N/A"}`,
        "",
        `Action: ${cluster.trading_action || "N/A"}`,
        "",
        `Risk: ${cluster.risk_zh || "N/A"}`,
      );
      if (sources.length) {
        lines.push("", "Sources:", ...sources.slice(0, 12).map((url) => `- ${url}`));
      }
    }
  }

  if (pending.length) {
    lines.push("", "## Pending 但值得跟進", "", "以下內容尚未完成 full AI scoring，但 priority_score 顯示可能重要，digest 不應忽略。/ These are not fully analyzed yet.");
    for (const item of pending) {
      lines.push(
        "",
        `### @${item.author_handle} · Priority ${item.priority_score}`,
        `- Time: ${hktTime(item.tweet_created_at || item.inserted_at)} HKT`,
        `- Reason: ${(item.priority_reason ?? []).join(", ") || "N/A"}`,
        "",
        item.tweet_text,
        "",
        `Source: ${item.tweet_url}`,
      );
    }
  }
  return lines.join("\n");
}

async function getClusters(date: string): Promise<EventCluster[]> {
  const supabase = getSupabaseServerClient();
  const { start, end } = dateBounds(date);
  const { data, error } = await supabase
    .from("event_clusters")
    .select(
      "id,fingerprint,title,summary_zh,why_it_matters_zh,market_mechanism_zh,trading_action,risk_zh,impact_max,confidence_avg,confidence_max,source_quality,time_horizon,tickers,sectors,tweet_ids,source_handles,source_tweet_urls,source_count,first_seen_at,last_seen_at,last_tweet_created_at",
    )
    .gte("last_seen_at", start)
    .lt("last_seen_at", end)
    .order("last_seen_at", { ascending: true });

  if (error) throw new Error(error.message);
  return (data ?? []) as EventCluster[];
}

async function getPending(date: string): Promise<PendingTweet[]> {
  const supabase = getSupabaseServerClient();
  const { start, end } = dateBounds(date);
  const { data, error } = await supabase
    .from("tweet_queue")
    .select("tweet_id,author_handle,tweet_text,tweet_url,tweet_created_at,priority_score,priority_reason,inserted_at")
    .eq("status", "pending")
    .gte("priority_score", 50)
    .gte("tweet_created_at", start)
    .lt("tweet_created_at", end)
    .order("priority_score", { ascending: false })
    .limit(50);

  if (error) throw new Error(error.message);
  return (data ?? []) as PendingTweet[];
}

export default async function StudyPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const selectedDate = params.date || hktDateString();
  const [clusters, pending] = await Promise.all([getClusters(selectedDate), getPending(selectedDate)]);
  const markdown = buildMarkdown(selectedDate, clusters, pending);
  const tickers = uniq(clusters.flatMap((cluster) => cluster.tickers ?? []));
  const sectors = uniq(clusters.flatMap((cluster) => cluster.sectors ?? []));

  return (
    <main className="min-h-screen bg-[#05070a] text-zinc-100">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-5 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-zinc-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-violet-400">AI Study View</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-normal text-white sm:text-4xl">每日事件研究稿</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
              以 event cluster 為單位輸出，已合併相近 tweets，方便直接交俾 AI 做每日投資復盤。
            </p>
          </div>
          <nav className="flex flex-wrap gap-2 text-sm">
            <Link className="border border-zinc-700 px-3 py-2 text-zinc-200 hover:bg-zinc-900" href="/">Signals</Link>
            <Link className="border border-zinc-700 px-3 py-2 text-zinc-200 hover:bg-zinc-900" href={`/alerts?date=${selectedDate}`}>Alerts</Link>
            <Link className="border border-violet-500/50 bg-violet-950/30 px-3 py-2 text-violet-100" href={`/study?date=${selectedDate}`}>Study</Link>
            <Link className="border border-zinc-700 px-3 py-2 text-zinc-200 hover:bg-zinc-900" href="/polymarket">Polymarket</Link>
          </nav>
        </header>

        <section className="grid gap-3 border border-zinc-800 bg-zinc-950/70 p-4 lg:grid-cols-[1fr_420px]">
          <form className="flex flex-col gap-2 sm:flex-row sm:items-end" action="/study">
            <label className="text-sm text-zinc-400">
              HKT 日期
              <input className="mt-1 block h-10 border border-zinc-700 bg-black px-3 font-mono text-sm text-white" type="date" name="date" defaultValue={selectedDate} />
            </label>
            <button className="h-10 border border-zinc-700 px-4 text-sm text-zinc-100 hover:bg-zinc-900" type="submit">載入</button>
          </form>
          <div className="grid grid-cols-4 gap-2 text-right">
            <div className="border border-zinc-800 bg-black/20 px-3 py-2">
              <p className="font-mono text-xl font-semibold text-white">{clusters.length}</p>
              <p className="text-xs text-zinc-500">Clusters</p>
            </div>
            <div className="border border-zinc-800 bg-black/20 px-3 py-2">
              <p className="font-mono text-xl font-semibold text-white">{pending.length}</p>
              <p className="text-xs text-zinc-500">Pending</p>
            </div>
            <div className="border border-zinc-800 bg-black/20 px-3 py-2">
              <p className="font-mono text-xl font-semibold text-white">{tickers.length}</p>
              <p className="text-xs text-zinc-500">Tickers</p>
            </div>
            <div className="border border-zinc-800 bg-black/20 px-3 py-2">
              <p className="font-mono text-xl font-semibold text-white">{sectors.length}</p>
              <p className="text-xs text-zinc-500">Sectors</p>
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <aside className="space-y-4 border border-zinc-800 bg-zinc-950/70 p-4">
            <div>
              <p className="text-xs font-semibold text-zinc-500">Tickers</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {tickers.length ? tickers.map((ticker) => <span key={ticker} className="border border-cyan-500/30 bg-cyan-950/30 px-2 py-1 font-mono text-xs text-cyan-100">{ticker}</span>) : <span className="text-sm text-zinc-500">N/A</span>}
              </div>
            </div>
            <div>
              <p className="text-xs font-semibold text-zinc-500">Sectors</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {sectors.length ? sectors.map((sector) => <span key={sector} className="border border-emerald-500/30 bg-emerald-950/30 px-2 py-1 text-xs text-emerald-100">{sector}</span>) : <span className="text-sm text-zinc-500">N/A</span>}
              </div>
            </div>
            <p className="text-xs leading-5 text-zinc-500">
              呢個 Markdown 已按時段整理 event clusters，包含 source count、ticker、sector、confidence、time horizon、action 同 source links。
            </p>
          </aside>

          <div className="min-w-0 border border-zinc-800 bg-black/40">
            <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
              <p className="font-mono text-xs uppercase text-zinc-500">Cluster Markdown Export</p>
              <CopyMarkdownButton value={markdown} />
            </div>
            <textarea
              className="min-h-[720px] w-full resize-y bg-transparent p-4 font-mono text-sm leading-6 text-zinc-100 outline-none"
              readOnly
              value={markdown}
            />
          </div>
        </section>
      </div>
    </main>
  );
}
