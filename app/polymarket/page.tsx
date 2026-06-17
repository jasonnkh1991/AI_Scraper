import Link from "next/link";
import { getSupabaseServerClient } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type Signal = {
  id: number;
  market_id: string;
  question: string;
  signal_type: string;
  old_probability: number | null;
  new_probability: number | null;
  probability_change: number | null;
  window_minutes: number | null;
  volume_24hr: number | null;
  liquidity: number | null;
  spread: number | null;
  quality_score: number | null;
  market_implication_zh: string | null;
  trading_lens_zh: string | null;
  source_url: string | null;
  sent_to_telegram: boolean;
  created_at: string;
};

type Market = {
  market_id: string;
  question: string;
  category: string | null;
  tags: string[] | null;
  source: string;
  discovery_score: number;
  source_url: string | null;
  last_snapshot_at: string | null;
};

function pct(value: number | null) {
  if (value === null || value === undefined) return "N/A";
  return `${Math.round(value * 100)}%`;
}

function signedPct(value: number | null) {
  if (value === null || value === undefined) return "N/A";
  const sign = value > 0 ? "+" : "";
  return `${sign}${Math.round(value * 100)} pts`;
}

function hktTime(value: string | null) {
  if (!value) return "N/A";
  return new Intl.DateTimeFormat("zh-HK", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Hong_Kong",
  }).format(new Date(value));
}

function qualityClass(score: number | null) {
  if ((score ?? 0) >= 85) return "border-red-500/60 bg-red-950/30 text-red-100";
  if ((score ?? 0) >= 70) return "border-orange-500/60 bg-orange-950/30 text-orange-100";
  return "border-zinc-700 bg-zinc-950 text-zinc-300";
}

async function getSignals(): Promise<Signal[]> {
  const supabase = getSupabaseServerClient();
  const { data, error } = await supabase
    .from("polymarket_signals")
    .select("id,market_id,question,signal_type,old_probability,new_probability,probability_change,window_minutes,volume_24hr,liquidity,spread,quality_score,market_implication_zh,trading_lens_zh,source_url,sent_to_telegram,created_at")
    .order("created_at", { ascending: false })
    .limit(60);
  if (error) throw new Error(error.message);
  return (data ?? []) as Signal[];
}

async function getMarkets(): Promise<Market[]> {
  const supabase = getSupabaseServerClient();
  const { data, error } = await supabase
    .from("polymarket_markets")
    .select("market_id,question,category,tags,source,discovery_score,source_url,last_snapshot_at")
    .eq("active", true)
    .eq("closed", false)
    .order("discovery_score", { ascending: false })
    .limit(40);
  if (error) throw new Error(error.message);
  return (data ?? []) as Market[];
}

export default async function PolymarketPage() {
  const [signals, markets] = await Promise.all([getSignals(), getMarkets()]);
  const latestQuality = signals[0]?.quality_score ?? null;

  return (
    <main className="min-h-screen bg-[#05070a] text-zinc-100">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-5 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-zinc-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-emerald-400">Polymarket Radar</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-normal text-white sm:text-4xl">概率市場異動</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
              監控 Polymarket 隱含機率、流動性及成交量，捕捉宏觀、政策、地緣、AI、Crypto 事件重新定價。
            </p>
          </div>
          <nav className="flex flex-wrap gap-2 text-sm">
            <Link className="border border-zinc-700 px-3 py-2 text-zinc-200 hover:bg-zinc-900" href="/">Signals</Link>
            <Link className="border border-zinc-700 px-3 py-2 text-zinc-200 hover:bg-zinc-900" href="/study">Study</Link>
            <Link className="border border-emerald-500/50 bg-emerald-950/30 px-3 py-2 text-emerald-100" href="/polymarket">Polymarket</Link>
          </nav>
        </header>

        <section className="grid gap-3 md:grid-cols-3">
          <div className="border border-zinc-800 bg-zinc-950/70 p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-zinc-500">Signals</p>
            <p className="mt-2 font-mono text-3xl font-semibold text-white">{signals.length}</p>
          </div>
          <div className="border border-zinc-800 bg-zinc-950/70 p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-zinc-500">Active Markets</p>
            <p className="mt-2 font-mono text-3xl font-semibold text-white">{markets.length}</p>
          </div>
          <div className={`border p-4 ${qualityClass(latestQuality)}`}>
            <p className="text-xs uppercase tracking-[0.18em] opacity-70">Latest Quality</p>
            <p className="mt-2 font-mono text-3xl font-semibold">{latestQuality ?? "N/A"}</p>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[1fr_360px]">
          <div className="flex flex-col gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-zinc-400">Probability Shocks</h2>
            {signals.length === 0 ? (
              <div className="border border-zinc-800 bg-zinc-950/70 p-6 text-sm text-zinc-400">暫時未有 Polymarket signal。首次部署後通常要至少兩個 snapshot 才能比較變化。</div>
            ) : signals.map((signal) => (
              <article key={signal.id} className="border border-zinc-800 bg-zinc-950/80 p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="font-mono text-xs text-zinc-500">{hktTime(signal.created_at)} HKT · {signal.signal_type}</p>
                    <h3 className="mt-1 text-lg font-semibold leading-7 text-white">{signal.question}</h3>
                  </div>
                  <div className={`shrink-0 border px-3 py-2 text-right font-mono ${qualityClass(signal.quality_score)}`}>
                    <p className="text-xs opacity-70">Quality</p>
                    <p className="text-xl font-semibold">{signal.quality_score ?? "N/A"}</p>
                  </div>
                </div>
                <div className="mt-4 grid gap-2 sm:grid-cols-4">
                  <div className="border border-zinc-800 bg-black/20 p-3"><p className="text-xs text-zinc-500">Old</p><p className="font-mono text-lg">{pct(signal.old_probability)}</p></div>
                  <div className="border border-zinc-800 bg-black/20 p-3"><p className="text-xs text-zinc-500">New</p><p className="font-mono text-lg">{pct(signal.new_probability)}</p></div>
                  <div className="border border-zinc-800 bg-black/20 p-3"><p className="text-xs text-zinc-500">Move</p><p className="font-mono text-lg">{signedPct(signal.probability_change)}</p></div>
                  <div className="border border-zinc-800 bg-black/20 p-3"><p className="text-xs text-zinc-500">Window</p><p className="font-mono text-lg">{signal.window_minutes ?? "N/A"}m</p></div>
                </div>
                <div className="mt-4 grid gap-3 text-sm leading-6 text-zinc-300 md:grid-cols-2">
                  <p><span className="text-zinc-500">重要性：</span>{signal.market_implication_zh || "N/A"}</p>
                  <p><span className="text-zinc-500">交易觀察：</span>{signal.trading_lens_zh || "N/A"}</p>
                </div>
                {signal.source_url ? <a className="mt-4 inline-flex border border-zinc-700 px-3 py-2 text-sm text-emerald-200 hover:bg-emerald-950/30" href={signal.source_url} target="_blank" rel="noreferrer">Open Polymarket</a> : null}
              </article>
            ))}
          </div>

          <aside className="flex flex-col gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-zinc-400">Active Watchlist</h2>
            {markets.map((market) => (
              <article key={market.market_id} className="border border-zinc-800 bg-zinc-950/70 p-3">
                <p className="font-mono text-xs text-zinc-500">Score {market.discovery_score} · {market.source}</p>
                <h3 className="mt-1 text-sm font-semibold leading-6 text-white">{market.question}</h3>
                <p className="mt-2 text-xs text-zinc-500">Last snapshot: {hktTime(market.last_snapshot_at)}</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {(market.tags ?? []).slice(0, 4).map((tag) => <span key={tag} className="border border-zinc-800 px-2 py-1 text-xs text-zinc-400">{tag}</span>)}
                </div>
              </article>
            ))}
          </aside>
        </section>
      </div>
    </main>
  );
}
