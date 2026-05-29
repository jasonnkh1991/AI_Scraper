import Link from "next/link";
import { CopyMarkdownButton } from "./CopyMarkdownButton";
import { getSupabaseServerClient } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type SearchParams = Promise<{ date?: string }>;

type StudyBrief = {
  study_date: string;
  timezone: string;
  title: string;
  brief_markdown: string;
  alert_count: number;
  tickers: string[] | null;
  sectors: string[] | null;
  source_tweet_urls: string[] | null;
  updated_at: string;
};

type TelegramAlert = {
  id: number;
  alert_type: string;
  title: string;
  message_markdown: string;
  source_tweet_urls: string[] | null;
  impact_max: number | null;
  confidence_avg: number | null;
  tickers: string[] | null;
  sectors: string[] | null;
  period_start: string | null;
  created_at: string;
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

function fallbackBrief(date: string, alerts: TelegramAlert[]) {
  const lines = [`# Daily Market Study Brief - ${date} HKT`, "", `Alerts archived: ${alerts.length}`];
  const grouped = alerts.reduce<Record<string, TelegramAlert[]>>((acc, alert) => {
    const label = periodLabel(alert.period_start || alert.created_at);
    acc[label] = acc[label] || [];
    acc[label].push(alert);
    return acc;
  }, {});

  if (alerts.length === 0) {
    lines.push("", "No archived Telegram alerts for this date yet.");
    return lines.join("\n");
  }

  for (const [period, items] of Object.entries(grouped)) {
    lines.push("", `## ${period}`);
    for (const alert of items) {
      lines.push(
        "",
        `### ${alert.title}`,
        `- Type: ${alert.alert_type}`,
        `- Impact max: ${alert.impact_max ?? "N/A"}`,
        `- Confidence avg: ${alert.confidence_avg ?? "N/A"}`,
        `- Tickers: ${(alert.tickers ?? []).join(", ") || "N/A"}`,
        `- Sectors: ${(alert.sectors ?? []).join(", ") || "N/A"}`,
        "",
        alert.message_markdown,
      );
      const sources = alert.source_tweet_urls ?? [];
      if (sources.length) {
        lines.push("", "Sources:", ...sources.slice(0, 12).map((url) => `- ${url}`));
      }
    }
  }
  return lines.join("\n");
}

async function getStudy(date: string): Promise<{ brief: StudyBrief | null; fallback: string; alerts: TelegramAlert[] }> {
  const supabase = getSupabaseServerClient();
  const { data: briefData } = await supabase
    .from("daily_study_briefs")
    .select("study_date,timezone,title,brief_markdown,alert_count,tickers,sectors,source_tweet_urls,updated_at")
    .eq("study_date", date)
    .maybeSingle();

  const { start, end } = dateBounds(date);
  const { data: alertsData, error } = await supabase
    .from("telegram_alerts")
    .select("id,alert_type,title,message_markdown,source_tweet_urls,impact_max,confidence_avg,tickers,sectors,period_start,created_at")
    .gte("created_at", start)
    .lt("created_at", end)
    .order("created_at", { ascending: true });

  if (error) throw new Error(error.message);
  const alerts = (alertsData ?? []) as TelegramAlert[];
  return {
    brief: (briefData as StudyBrief | null) ?? null,
    fallback: fallbackBrief(date, alerts),
    alerts,
  };
}

export default async function StudyPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const selectedDate = params.date || hktDateString();
  const { brief, fallback, alerts } = await getStudy(selectedDate);
  const markdown = brief?.brief_markdown || fallback;
  const tickers = brief?.tickers ?? Array.from(new Set(alerts.flatMap((alert) => alert.tickers ?? [])));
  const sectors = brief?.sectors ?? Array.from(new Set(alerts.flatMap((alert) => alert.sectors ?? [])));

  return (
    <main className="min-h-screen bg-[#05070a] text-zinc-100">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-5 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-zinc-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-violet-400">AI Study View</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-normal text-white sm:text-4xl">每日 AI 研究稿</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
              乾淨 Markdown 輸出，專門俾你複製去 ChatGPT / Claude / Grok 做每日投資復盤。
            </p>
          </div>
          <nav className="flex flex-wrap gap-2 text-sm">
            <Link className="border border-zinc-700 px-3 py-2 text-zinc-200 hover:bg-zinc-900" href="/">Signals</Link>
            <Link className="border border-zinc-700 px-3 py-2 text-zinc-200 hover:bg-zinc-900" href={`/alerts?date=${selectedDate}`}>Alerts</Link>
            <Link className="border border-violet-500/50 bg-violet-950/30 px-3 py-2 text-violet-100" href={`/study?date=${selectedDate}`}>Study</Link>
          </nav>
        </header>

        <section className="grid gap-3 border border-zinc-800 bg-zinc-950/70 p-4 lg:grid-cols-[1fr_360px]">
          <form className="flex flex-col gap-2 sm:flex-row sm:items-end" action="/study">
            <label className="text-sm text-zinc-400">
              HKT 日期
              <input className="mt-1 block h-10 border border-zinc-700 bg-black px-3 font-mono text-sm text-white" type="date" name="date" defaultValue={selectedDate} />
            </label>
            <button className="h-10 border border-zinc-700 px-4 text-sm text-zinc-100 hover:bg-zinc-900" type="submit">載入</button>
          </form>
          <div className="grid grid-cols-3 gap-2 text-right">
            <div className="border border-zinc-800 bg-black/20 px-3 py-2">
              <p className="font-mono text-xl font-semibold text-white">{brief?.alert_count ?? alerts.length}</p>
              <p className="text-xs text-zinc-500">Alerts</p>
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

        <section className="grid gap-4 lg:grid-cols-[260px_1fr]">
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
              呢個 textarea 已經係 AI-ready 格式。全選複製後，可以直接叫 AI 分析今日主線、可交易 catalyst、風險同 next watchlist。
            </p>
          </aside>

          <div className="min-w-0 border border-zinc-800 bg-black/40">
            <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
              <p className="font-mono text-xs uppercase text-zinc-500">Markdown Export</p>
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
