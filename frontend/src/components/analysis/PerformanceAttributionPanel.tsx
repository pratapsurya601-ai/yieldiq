"use client"

/* ─────────────────────────────────────────────────────────────────
 * PerformanceAttributionPanel
 *
 * Episode-level track record for YIQ's verdict on a single ticker.
 * Shows realised alpha vs Nifty over the lookback window, the best
 * and worst single verdict, and a rolling 30-day sparkline of mean
 * alpha so the user can see how the call has trended.
 *
 * SEBI vocabulary discipline
 * --------------------------
 * Public copy uses "alpha", "excess return" and "direction correct".
 * Banned SEBI-advisory tokens (the usual set documented in
 * scripts/check_sebi_words.py BANNED_WORDS) never appear in any
 * shipped string. The hover-state labels are factual
 * ("12 of 18 verdicts direction-correct") not advisory.
 * ───────────────────────────────────────────────────────────────── */

import { useQuery } from "@tanstack/react-query"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts"
import {
  getVerdictAttribution,
  type VerdictAttributionEpisode,
  type VerdictAttributionRollingBucket,
  type VerdictAttributionSummary,
} from "@/lib/api"
import { cn } from "@/lib/utils"

interface Props {
  ticker: string
  lookbackDays?: number
}

/* Map raw model verdict -> SEBI-safe display string. Mirrors
 * backend/services/fv_accuracy_service.py (single source of truth).
 * No banned-token aliases here; pure factual descriptors. */
function displayVerdict(v: string | null | undefined): string {
  switch ((v ?? "").toLowerCase()) {
    case "undervalued":
      return "Below fair value"
    case "fairly_valued":
      return "Near fair value"
    case "overvalued":
      return "Above fair value"
    default:
      return "—"
  }
}

function formatPct(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  const sign = n > 0 ? "+" : ""
  return `${sign}${n.toFixed(digits)}%`
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  try {
    return new Date(iso).toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "2-digit",
    })
  } catch {
    return iso
  }
}

/* ─────────────────────────────────────────────────────────────────
 * Loading / empty placeholder. Keeping the slot occupied avoids the
 * layout jank pattern that bit us repeatedly on the analysis page.
 * ───────────────────────────────────────────────────────────────── */
function Placeholder({ variant }: { variant: "loading" | "empty" | "error" }) {
  return (
    <section
      data-testid="performance-attribution-panel"
      className="rounded-2xl border border-border bg-surface p-4"
    >
      <header className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ink">Performance attribution</h2>
        <span className="text-xs text-ink-muted">Excess return vs Nifty</span>
      </header>
      {variant === "loading" ? (
        <div className="h-40 animate-pulse rounded-xl bg-surface-2" />
      ) : (
        <p className="text-sm text-ink-muted">
          {variant === "empty"
            ? "Not enough verdict history to compute attribution yet."
            : "Attribution data unavailable right now."}
        </p>
      )}
    </section>
  )
}

/* ─────────────────────────────────────────────────────────────────
 * Callout card for a single verdict (best / worst). The colour
 * conveys sign of alpha; the verdict label is text, never a value
 * judgment.
 * ───────────────────────────────────────────────────────────────── */
function VerdictCallout({
  label,
  episode,
}: {
  label: string
  episode: VerdictAttributionEpisode
}) {
  const positive = episode.alpha_vs_nifty >= 0
  return (
    <div
      data-testid="verdict-callout"
      className={cn(
        "rounded-xl border p-3",
        positive
          ? "border-emerald-200 bg-emerald-50 dark:border-emerald-800/60 dark:bg-emerald-950/30"
          : "border-rose-200 bg-rose-50 dark:border-rose-800/60 dark:bg-rose-950/30",
      )}
    >
      <p className="text-[11px] uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 text-sm font-semibold text-ink">
        {displayVerdict(episode.verdict_at_start)} on {formatDate(episode.period_start)}
      </p>
      <p className="mt-2 font-mono text-lg">
        Alpha vs Nifty:{" "}
        <span className={positive ? "text-emerald-700 dark:text-emerald-300" : "text-rose-700 dark:text-rose-300"}>
          {formatPct(episode.alpha_vs_nifty)}
        </span>
      </p>
      <p className="mt-1 text-xs text-ink-muted">
        Actual {formatPct(episode.actual_return_pct)} vs Nifty {formatPct(episode.nifty_return_pct)}
        {" · "}window {formatDate(episode.period_start)} → {formatDate(episode.period_end)}
      </p>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────
 * Rolling 30d track-record chart. Uses Recharts line with a zero
 * reference for clarity. Empty rolling array renders nothing rather
 * than an empty axis pair.
 * ───────────────────────────────────────────────────────────────── */
function RollingTrackRecord({
  buckets,
}: {
  buckets: VerdictAttributionRollingBucket[]
}) {
  if (!buckets.length) return null
  const data = buckets.map(b => ({
    date: b.bucket_end,
    alpha: Number(b.mean_alpha_vs_nifty_pct.toFixed(2)),
    count: b.verdict_count,
  }))
  return (
    <div data-testid="rolling-track-record" className="mt-4">
      <p className="mb-2 text-xs font-medium text-ink-muted">
        Rolling 30-day mean alpha vs Nifty
      </p>
      <div className="h-32 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <XAxis
              dataKey="date"
              tickFormatter={iso => formatDate(iso)}
              tick={{ fontSize: 10 }}
              minTickGap={24}
            />
            <YAxis
              tickFormatter={(v: number) => `${v}%`}
              tick={{ fontSize: 10 }}
              width={36}
            />
            <ReferenceLine y={0} stroke="currentColor" strokeOpacity={0.3} />
            <Tooltip
              formatter={(value) => [formatPct(Number(value)), "Alpha vs Nifty"]}
              labelFormatter={iso => formatDate(String(iso))}
              contentStyle={{ fontSize: 12, borderRadius: 8 }}
            />
            <Line
              type="monotone"
              dataKey="alpha"
              stroke="currentColor"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────
 * Main panel
 * ───────────────────────────────────────────────────────────────── */
export default function PerformanceAttributionPanel({
  ticker,
  lookbackDays = 365,
}: Props) {
  const { data, isLoading, isError } = useQuery<VerdictAttributionSummary>({
    queryKey: ["verdict-attribution", ticker, lookbackDays],
    queryFn: () => getVerdictAttribution(ticker, lookbackDays),
    staleTime: 6 * 60 * 60 * 1000, // 6h — matches backend cache TTL
    retry: 1,
  })

  if (isLoading) return <Placeholder variant="loading" />
  if (isError || !data) return <Placeholder variant="error" />
  if (!data.total_verdicts_tracked) return <Placeholder variant="empty" />

  const positiveAlpha = data.avg_alpha_vs_nifty_pct >= 0
  const months = Math.max(1, Math.round(lookbackDays / 30))

  return (
    <section
      data-testid="performance-attribution-panel"
      className="rounded-2xl border border-border bg-surface p-4"
    >
      <header className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-ink">Performance attribution</h2>
          <p className="text-xs text-ink-muted">
            How YIQ&apos;s verdict on this ticker has fared vs Nifty over the last {months}mo
          </p>
        </div>
        <span
          className={cn(
            "rounded-full px-2.5 py-1 text-xs font-medium",
            positiveAlpha
              ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
              : "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300",
          )}
          data-testid="attribution-headline-chip"
        >
          {positiveAlpha ? "Positive alpha" : "Negative alpha"}
        </span>
      </header>

      {/* Headline statement — the single sentence the user reads first. */}
      <p
        data-testid="attribution-headline"
        className="text-base text-ink"
      >
        YIQ&apos;s verdict on this ticker delivered{" "}
        <span className={cn(
          "font-mono font-semibold",
          positiveAlpha ? "text-emerald-700 dark:text-emerald-300" : "text-rose-700 dark:text-rose-300",
        )}>
          {formatPct(data.avg_alpha_vs_nifty_pct)}
        </span>{" "}
        average excess return vs Nifty across {data.total_verdicts_tracked} verdict
        {data.total_verdicts_tracked === 1 ? "" : "s"} in the last {months} months.
      </p>

      {/* Secondary metrics row. */}
      <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div className="rounded-lg border border-border bg-surface-2 p-2">
          <dt className="text-ink-muted">Verdicts tracked</dt>
          <dd className="mt-1 font-mono text-sm text-ink">{data.total_verdicts_tracked}</dd>
        </div>
        <div className="rounded-lg border border-border bg-surface-2 p-2">
          <dt className="text-ink-muted">Direction correct</dt>
          <dd className="mt-1 font-mono text-sm text-ink">
            {data.direction_correct_pct.toFixed(0)}%
          </dd>
        </div>
        <div className="rounded-lg border border-border bg-surface-2 p-2">
          <dt className="text-ink-muted">Median alpha</dt>
          <dd className="mt-1 font-mono text-sm text-ink">
            {formatPct(data.median_alpha_vs_nifty_pct)}
          </dd>
        </div>
      </dl>

      {/* Best + worst callouts. */}
      {(data.best_verdict || data.worst_verdict) && (
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          {data.best_verdict && (
            <VerdictCallout label="Best single verdict" episode={data.best_verdict} />
          )}
          {data.worst_verdict && (
            <VerdictCallout label="Worst single verdict" episode={data.worst_verdict} />
          )}
        </div>
      )}

      <RollingTrackRecord buckets={data.rolling_30d_track_record} />

      <p className="mt-3 text-[11px] leading-relaxed text-ink-muted">
        Alpha = realised actual return minus an equal-weighted Nifty-top-5 proxy basket return over the
        same window. Past results do not predict future returns. YieldIQ is not a SEBI-registered
        Investment Adviser.
      </p>
    </section>
  )
}
