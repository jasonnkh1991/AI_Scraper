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
  const { data, error } = await supabase
    .from("insights")
    .select(
      "id,tweet_id,author_handle,author_name,tweet_text,tweet_url,tweet_created_at,impact_score,target_sectors,summary_zh,trading_action,inserted_at",
    )
    .order("tweet_created_at", { ascending: false, nullsFirst: false })
    .limit(100);

  if (error) {
    throw new Error(error.message);
  }

  return (data ?? []) as Insight[];
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
        </header>

        <section className="grid gap-3">
          {insights.length === 0 ? (
            <div className="border border-zinc-800 bg-zinc-950/70 p-8 text-center text-zinc-400">
              暫時未有高衝擊訊號。
            </div>
          ) : (
            insights.map((insight) => (
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
                  <p className="font-mono text-xs text-zinc-500">
                    {formatTime(insight.tweet_created_at)}
                  </p>
                </div>

                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`border px-2 py-1 font-mono text-xs font-semibold ${scoreClass(
                        insight.impact_score,
                      )}`}
                    >
                      {scoreLabel(insight.impact_score)} · {insight.impact_score}/10
                    </span>
                    {insight.target_sectors.map((sector) => (
                      <span
                        key={sector}
                        className="border border-emerald-500/30 bg-emerald-950/30 px-2 py-1 text-xs text-emerald-100"
                      >
                        {sector}
                      </span>
                    ))}
                  </div>

                  <p className="mt-3 text-base font-medium leading-7 text-zinc-100">
                    {insight.summary_zh}
                  </p>
                  <p className="mt-3 border-l-2 border-cyan-400/60 pl-3 text-sm leading-6 text-cyan-100">
                    {insight.trading_action}
                  </p>
                  <p className="mt-3 line-clamp-2 text-xs leading-5 text-zinc-500">
                    {insight.tweet_text}
                  </p>
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
            ))
          )}
        </section>
      </div>
    </main>
  );
}
