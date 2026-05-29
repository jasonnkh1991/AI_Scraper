import Link from "next/link";
import { getSupabaseServerClient } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type Insight = {
  id: number;
  tweet_id: string;
  author_handle: string;
  author_name: string | null;
  tweet_text: string;
  tweet_url: string;
  tweet_created_at: string | null;
  impact_score: number;
  target_sectors: string[];
  summary_zh: string;
  trading_action: string;
  original_zh: string | null;
  why_it_matters_zh: string | null;
  market_mechanism_zh: string | null;
  affected_tickers: string[] | null;
  confidence_score: number | null;
  time_horizon: string | null;
  source_quality: string | null;
  risk_zh: string | null;
  inserted_at: string;
};

function scoreClass(score: number) {
  if (score >= 9) return "border-red-500/50 bg-red-950/45 text-red-100";
  return "border-orange-400/50 bg-orange-950/40 text-orange-100";
}

function scoreLabel(score: number) {
  if (score >= 9) return "極高衝擊";
  return "高衝擊";
}

function confidenceClass(score: number | null) {
  if (!score) return "border-zinc-700 bg-zinc-900 text-zinc-300";
  if (score >= 8) return "border-emerald-500/40 bg-emerald-950/30 text-emerald-100";
  if (score >= 6) return "border-yellow-500/40 bg-yellow-950/30 text-yellow-100";
  return "border-zinc-700 bg-zinc-900 text-zinc-300";
}

function labelValue(value: string | null | undefined) {
  if (!value) return "未分類";
  return value.replace(/_/g, " ");
}

function formatTime(value: string | null) {
  if (!value) return "時間未知";
  return new Intl.DateTimeFormat("zh-HK", {
    dateStyle: "medium",
    timeStyle: "short",
    hour12: false,
    timeZone: "Asia/Hong_Kong",
  }).format(new Date(value));
}

async function getInsights(): Promise<Insight[]> {
  const supabase = getSupabaseServerClient();
  const fullColumns =
    "id,tweet_id,author_handle,author_name,tweet_text,tweet_url,tweet_created_at,impact_score,target_sectors,summary_zh,trading_action,original_zh,why_it_matters_zh,market_mechanism_zh,affected_tickers,confidence_score,time_horizon,source_quality,risk_zh,inserted_at";
  const legacyColumns =
    "id,tweet_id,author_handle,author_name,tweet_text,tweet_url,tweet_created_at,impact_score,target_sectors,summary_zh,trading_action,inserted_at";

  const query = (columns: string) =>
    supabase
      .from("insights")
      .select(columns)
      .order("tweet_created_at", { ascending: false, nullsFirst: false })
      .limit(100);

  const { data, error } = await query(fullColumns);

  if (!error) {
    return (data ?? []) as Insight[];
  }

  const legacy = await query(legacyColumns);
  if (legacy.error) {
    throw new Error(legacy.error.message);
  }

  const legacyRows = (legacy.data ?? []) as Omit<
    Insight,
    | "original_zh"
    | "why_it_matters_zh"
    | "market_mechanism_zh"
    | "affected_tickers"
    | "confidence_score"
    | "time_horizon"
    | "source_quality"
    | "risk_zh"
  >[];

  return legacyRows.map((item) => ({
    ...item,
    original_zh: null,
    why_it_matters_zh: null,
    market_mechanism_zh: null,
    affected_tickers: [],
    confidence_score: null,
    time_horizon: null,
    source_quality: null,
    risk_zh: null,
  }));
}

export default async function DashboardPage() {
  const insights = await getInsights();
  const latest = insights[0];
  const maxScore = insights.reduce((max, item) => Math.max(max, item.impact_score), 0);

  return (
    <main className="min-h-screen bg-[#05070a] text-zinc-100">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-5 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-zinc-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-emerald-400">
              AI Market Signal Monitor
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-normal text-white sm:text-4xl">
              市場情報雷達
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
              只顯示 AI 判定有明確市場衝擊嘅 X List 訊號，低質傳聞同社交噪音已經過濾。
            </p>
          </div>

          <div className="flex flex-col gap-3 lg:items-end">
            <nav className="flex flex-wrap gap-2 text-sm">
              <Link className="border border-emerald-500/50 bg-emerald-950/30 px-3 py-2 text-emerald-100" href="/">
                Signals
              </Link>
              <Link className="border border-zinc-700 px-3 py-2 text-zinc-200 hover:bg-zinc-900" href="/alerts">
                Alerts
              </Link>
              <Link className="border border-zinc-700 px-3 py-2 text-zinc-200 hover:bg-zinc-900" href="/study">
                Study
              </Link>
            </nav>

            <div className="grid grid-cols-3 gap-2 text-right sm:min-w-[420px]">
            <div className="border border-zinc-800 bg-zinc-950/70 px-3 py-3">
              <p className="font-mono text-2xl font-semibold text-white">{insights.length}</p>
              <p className="mt-1 text-xs text-zinc-500">訊號數</p>
            </div>
            <div className="border border-zinc-800 bg-zinc-950/70 px-3 py-3">
              <p className="font-mono text-2xl font-semibold text-white">{maxScore || "-"}</p>
              <p className="mt-1 text-xs text-zinc-500">最高分</p>
            </div>
            <div className="border border-zinc-800 bg-zinc-950/70 px-3 py-3">
              <p className="font-mono text-sm font-semibold text-white">
                {latest ? formatTime(latest.tweet_created_at) : "-"}
              </p>
              <p className="mt-1 text-xs text-zinc-500">最新 Tweet</p>
            </div>
          </div>
          </div>
        </header>

        <section className="grid gap-3">
          {insights.length === 0 ? (
            <div className="border border-zinc-800 bg-zinc-950/70 p-8 text-center text-zinc-400">
              暫時未有高衝擊訊號。
            </div>
          ) : (
            insights.map((insight) => {
              const tickers = insight.affected_tickers ?? [];

              return (
                <article
                  key={insight.tweet_id}
                  className="grid gap-4 border border-zinc-800 bg-zinc-950/70 p-4 transition-colors hover:border-zinc-700 lg:grid-cols-[180px_1fr_180px]"
                >
                  <div className="flex flex-row justify-between gap-3 lg:flex-col lg:justify-start">
                    <div>
                      <p className="text-sm font-semibold text-white">
                        @{insight.author_handle}
                      </p>
                      <p className="mt-1 line-clamp-1 text-xs text-zinc-500">
                        {insight.author_name ?? "Unknown"}
                      </p>
                    </div>
                    <div className="space-y-2">
                      <p className="font-mono text-xs text-zinc-500">
                        {formatTime(insight.tweet_created_at)}
                      </p>
                      <span
                        className={`inline-flex border px-2 py-1 font-mono text-xs ${confidenceClass(
                          insight.confidence_score,
                        )}`}
                      >
                        CONF {insight.confidence_score ?? "-"}/10
                      </span>
                    </div>
                  </div>

                  <div className="min-w-0 space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`border px-2 py-1 font-mono text-xs font-semibold ${scoreClass(
                          insight.impact_score,
                        )}`}
                      >
                        {scoreLabel(insight.impact_score)} · {insight.impact_score}/10
                      </span>
                      <span className="border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-300">
                        {labelValue(insight.source_quality)}
                      </span>
                      <span className="border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-300">
                        {labelValue(insight.time_horizon)}
                      </span>
                      {insight.target_sectors.map((sector) => (
                        <span
                          key={sector}
                          className="border border-emerald-500/30 bg-emerald-950/30 px-2 py-1 text-xs text-emerald-100"
                        >
                          {sector}
                        </span>
                      ))}
                      {tickers.map((ticker) => (
                        <span
                          key={ticker}
                          className="border border-cyan-500/30 bg-cyan-950/30 px-2 py-1 font-mono text-xs text-cyan-100"
                        >
                          {ticker}
                        </span>
                      ))}
                    </div>

                    <p className="text-base font-medium leading-7 text-zinc-100">
                      {insight.summary_zh}
                    </p>

                    <div className="grid gap-3 xl:grid-cols-2">
                      <div className="border border-zinc-800 bg-black/20 p-3">
                        <p className="text-xs font-semibold text-zinc-500">原文翻譯</p>
                        <p className="mt-2 text-sm leading-6 text-zinc-200">
                          {insight.original_zh || insight.tweet_text}
                        </p>
                      </div>
                      <div className="border border-zinc-800 bg-black/20 p-3">
                        <p className="text-xs font-semibold text-zinc-500">點解重要</p>
                        <p className="mt-2 text-sm leading-6 text-zinc-200">
                          {insight.why_it_matters_zh || insight.trading_action}
                        </p>
                      </div>
                    </div>

                    <p className="border-l-2 border-cyan-400/60 pl-3 text-sm leading-6 text-cyan-100">
                      {insight.market_mechanism_zh || insight.trading_action}
                    </p>
                    <p className="border-l-2 border-orange-400/60 pl-3 text-sm leading-6 text-orange-100">
                      {insight.trading_action}
                    </p>
                    {insight.risk_zh ? (
                      <p className="text-xs leading-5 text-zinc-500">
                        反面風險：{insight.risk_zh}
                      </p>
                    ) : null}
                  </div>

                  <div className="flex items-end justify-start lg:justify-end">
                    <a
                      href={insight.tweet_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex h-10 items-center border border-zinc-700 px-3 text-sm font-medium text-zinc-100 transition-colors hover:border-zinc-500 hover:bg-zinc-900"
                    >
                      查看原 Tweet
                    </a>
                  </div>
                </article>
              );
            })
          )}
        </section>
      </div>
    </main>
  );
}
