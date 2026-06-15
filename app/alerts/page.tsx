import Link from "next/link";
import { getSupabaseServerClient } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type SearchParams = Promise<{ date?: string }>;

type TelegramAlert = {
  id: number;
  alert_type: string;
  session_id: string | null;
  period_start: string | null;
  period_end: string | null;
  title: string;
  message_markdown: string;
  source_tweet_urls: string[] | null;
  impact_max: number | null;
  confidence_avg: number | null;
  tickers: string[] | null;
  sectors: string[] | null;
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

function formatTime(value: string | null) {
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

function badgeClass(type: string) {
  if (type === "overnight_digest") return "border-cyan-500/40 bg-cyan-950/30 text-cyan-100";
  if (type === "session_header") return "border-zinc-700 bg-zinc-900 text-zinc-300";
  if (type === "single_alert") return "border-red-500/40 bg-red-950/30 text-red-100";
  return "border-orange-500/40 bg-orange-950/30 text-orange-100";
}

async function getAlerts(date: string): Promise<TelegramAlert[]> {
  const supabase = getSupabaseServerClient();
  const { start, end } = dateBounds(date);
  const { data, error } = await supabase
    .from("telegram_alerts")
    .select(
      "id,alert_type,session_id,period_start,period_end,title,message_markdown,source_tweet_urls,impact_max,confidence_avg,tickers,sectors,created_at",
    )
    .gte("created_at", start)
    .lt("created_at", end)
    .order("created_at", { ascending: false });

  if (error) throw new Error(error.message);
  return (data ?? []) as TelegramAlert[];
}

export default async function AlertsPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const selectedDate = params.date || hktDateString();
  const alerts = await getAlerts(selectedDate);
  const grouped = alerts.reduce<Record<string, TelegramAlert[]>>((acc, alert) => {
    const label = periodLabel(alert.period_start || alert.created_at);
    acc[label] = acc[label] || [];
    acc[label].push(alert);
    return acc;
  }, {});

  return (
    <main className="min-h-screen bg-[#05070a] text-zinc-100">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-5 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-zinc-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-cyan-400">Telegram Archive</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-normal text-white sm:text-4xl">Alert 記錄庫</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
              呢度只記錄實際 send 過去 Telegram 嘅內容，按香港時間日期同時段分組。
            </p>
          </div>
          <nav className="flex flex-wrap gap-2 text-sm">
            <Link className="border border-zinc-700 px-3 py-2 text-zinc-200 hover:bg-zinc-900" href="/">Signals</Link>
            <Link className="border border-cyan-500/50 bg-cyan-950/30 px-3 py-2 text-cyan-100" href={`/alerts?date=${selectedDate}`}>Alerts</Link>
            <Link className="border border-zinc-700 px-3 py-2 text-zinc-200 hover:bg-zinc-900" href={`/study?date=${selectedDate}`}>Study</Link>
            <Link className="border border-zinc-700 px-3 py-2 text-zinc-200 hover:bg-zinc-900" href="/polymarket">Polymarket</Link>
          </nav>
        </header>

        <section className="flex flex-col gap-3 border border-zinc-800 bg-zinc-950/70 p-4 sm:flex-row sm:items-end sm:justify-between">
          <form className="flex flex-col gap-2 sm:flex-row sm:items-end" action="/alerts">
            <label className="text-sm text-zinc-400">
              HKT 日期
              <input
                className="mt-1 block h-10 border border-zinc-700 bg-black px-3 font-mono text-sm text-white"
                type="date"
                name="date"
                defaultValue={selectedDate}
              />
            </label>
            <button className="h-10 border border-zinc-700 px-4 text-sm text-zinc-100 hover:bg-zinc-900" type="submit">
              載入
            </button>
          </form>
          <div className="grid grid-cols-2 gap-2 text-right sm:min-w-[260px]">
            <div className="border border-zinc-800 bg-black/20 px-3 py-2">
              <p className="font-mono text-xl font-semibold text-white">{alerts.length}</p>
              <p className="text-xs text-zinc-500">Telegram 訊息</p>
            </div>
            <div className="border border-zinc-800 bg-black/20 px-3 py-2">
              <p className="font-mono text-xl font-semibold text-white">{Object.keys(grouped).length}</p>
              <p className="text-xs text-zinc-500">時段</p>
            </div>
          </div>
        </section>

        {alerts.length === 0 ? (
          <section className="border border-zinc-800 bg-zinc-950/70 p-8 text-center text-zinc-400">
            呢日暫時未有 Telegram archive。新 schema apply 後，之後 send 出去嘅訊息會自動落呢度。
          </section>
        ) : (
          Object.entries(grouped).map(([period, items]) => (
            <section key={period} className="grid gap-3">
              <div className="flex items-center justify-between border-b border-zinc-800 pb-2">
                <h2 className="text-lg font-semibold text-white">{period}</h2>
                <span className="font-mono text-xs text-zinc-500">{items.length} alerts</span>
              </div>
              {items.map((alert) => (
                <article key={alert.id} className="grid gap-4 border border-zinc-800 bg-zinc-950/70 p-4 lg:grid-cols-[180px_1fr]">
                  <div className="space-y-3">
                    <span className={`inline-flex border px-2 py-1 font-mono text-xs ${badgeClass(alert.alert_type)}`}>
                      {alert.alert_type}
                    </span>
                    <div>
                      <p className="font-mono text-sm text-white">{formatTime(alert.created_at)}</p>
                      <p className="mt-1 text-xs text-zinc-500">{alert.session_id || "no-session"}</p>
                    </div>
                    {alert.impact_max ? <p className="font-mono text-sm text-orange-100">Impact {alert.impact_max}/10</p> : null}
                    {alert.confidence_avg ? <p className="font-mono text-sm text-emerald-100">Conf {alert.confidence_avg}/10</p> : null}
                  </div>
                  <div className="min-w-0 space-y-3">
                    <h3 className="text-lg font-semibold text-white">{alert.title}</h3>
                    <div className="flex flex-wrap gap-2">
                      {(alert.tickers ?? []).map((ticker) => (
                        <span key={ticker} className="border border-cyan-500/30 bg-cyan-950/30 px-2 py-1 font-mono text-xs text-cyan-100">{ticker}</span>
                      ))}
                      {(alert.sectors ?? []).map((sector) => (
                        <span key={sector} className="border border-emerald-500/30 bg-emerald-950/30 px-2 py-1 text-xs text-emerald-100">{sector}</span>
                      ))}
                    </div>
                    <pre className="whitespace-pre-wrap break-words border border-zinc-800 bg-black/25 p-3 text-sm leading-6 text-zinc-200">
                      {alert.message_markdown}
                    </pre>
                    {(alert.source_tweet_urls ?? []).length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {(alert.source_tweet_urls ?? []).slice(0, 8).map((url, index) => (
                          <a key={`${alert.id}-${url}`} className="border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900" href={url} target="_blank" rel="noreferrer">
                            Source {index + 1}
                          </a>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </article>
              ))}
            </section>
          ))
        )}
      </div>
    </main>
  );
}
