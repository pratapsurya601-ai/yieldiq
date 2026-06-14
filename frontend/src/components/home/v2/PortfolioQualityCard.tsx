"use client"
// Portfolio Quality Card — at-a-glance "quality posture" panel on /home.
//
// Consolidates the five quality signals YieldIQ already computes per ticker —
// YieldIQ Score (0-100), Margin of Safety (%), Piotroski F-score (0-9),
// confidence (%), and moat label (None / Narrow / Wide) — into a single
// dense surface for the user's portfolio holdings. Previously these were
// scattered across the per-analysis page; this card surfaces the cohort-
// level view so the user can see their portfolio's average score / MoS /
// Piotroski / confidence and the moat distribution without clicking into
// each position one by one.
//
// Data sources (reuses existing endpoints — no new backend):
//   - GET /api/v1/portfolio/holdings-live   → list of user's holdings
//   - GET /api/v1/public/stock-summary/{T}  → per-ticker StockSummary with
//     score / mos / piotroski / confidence / moat (one call per holding,
//     batched in parallel via useQueries)
//
// Cache: 5 min staleTime — quality signals are bhavcopy-driven, they do
// not move tick-by-tick.
//
// SEBI compliance: every label is observational ("posture", "signals")
// or a model output (the traffic-light dots). No "your portfolio is
// healthy / risky framing, no transactional language, no // sebi-allow: buy, sell
// observational verbs only — banned vocabulary handled by // sebi-allow: appears, should
// check_sebi_words.py.

import Link from "next/link"
import { useQuery, useQueries } from "@tanstack/react-query"
import { BarChart3 } from "lucide-react"
import PressScale from "@/components/motion/PressScale"
import {
  getHoldingsLive,
  getStockSummary,
  type LiveHolding,
  type StockSummary,
} from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { displayMos, computeTrueMos } from "@/lib/utils"
import TickerAvatar from "@/components/common/TickerAvatar"

// ── Thresholds ─────────────────────────────────────────────────────
// Single source of truth for traffic-light banding. The exact bands are
// documented in the PR body so QA / methodology can reproduce them.
type Light = "green" | "amber" | "red"

function scoreLight(score: number | null | undefined): Light | null {
  if (score == null || !Number.isFinite(score)) return null
  if (score >= 70) return "green"
  if (score >= 50) return "amber"
  return "red"
}

function mosLight(mos: number | null | undefined): Light | null {
  if (mos == null || !Number.isFinite(mos)) return null
  if (mos >= 20) return "green"
  if (mos >= 0) return "amber"
  return "red"
}

function piotroskiLight(p: number | null | undefined): Light | null {
  if (p == null || !Number.isFinite(p)) return null
  if (p >= 7) return "green"
  if (p >= 5) return "amber"
  return "red"
}

function confidenceLight(c: number | null | undefined): Light | null {
  if (c == null || !Number.isFinite(c)) return null
  if (c >= 80) return "green"
  if (c >= 60) return "amber"
  return "red"
}

function moatLight(moat: string | null | undefined): Light | null {
  if (!moat) return null
  const norm = moat.toLowerCase()
  if (norm === "wide") return "green"
  if (norm === "narrow") return "amber"
  return "red"
}

// Three-dot traffic light row. We pick the three most actionable signals
// for the per-row glance: Score, MoS, Piotroski. Confidence + Moat are
// already visible as their own columns so doubling them up in dots adds
// no information.
function TrafficLights({
  score,
  mos,
  piotroski,
}: {
  score: number | null | undefined
  mos: number | null | undefined
  piotroski: number | null | undefined
}) {
  const dots: Light[] = [
    scoreLight(score) ?? "red",
    mosLight(mos) ?? "red",
    piotroskiLight(piotroski) ?? "red",
  ]
  return (
    <span className="inline-flex items-center gap-1" data-testid="quality-traffic-lights">
      {dots.map((d, i) => (
        <span
          key={i}
          className={`w-2 h-2 rounded-full ${
            d === "green"
              ? "bg-green-500"
              : d === "amber"
                ? "bg-amber-500"
                : "bg-red-500"
          }`}
          aria-hidden
        />
      ))}
    </span>
  )
}

function MoatPill({ moat }: { moat: string | null | undefined }) {
  const light = moatLight(moat)
  const label = moat ? moat[0].toUpperCase() + moat.slice(1).toLowerCase() : "—"
  if (!light) {
    return <span className="text-caption font-mono text-[11px]">—</span>
  }
  const tone =
    light === "green"
      ? "bg-green-50 text-green-700 border-green-200 dark:bg-green-950/30 dark:text-green-400 dark:border-green-900"
      : light === "amber"
        ? "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/30 dark:text-amber-400 dark:border-amber-900"
        : "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/30 dark:text-red-400 dark:border-red-900"
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 text-[10px] font-semibold border rounded ${tone}`}
    >
      {label}
    </span>
  )
}

// Coloured number cell — the value plus a tone derived from the same
// threshold bands the traffic lights use. Falls back to a neutral em-
// dash when the underlying summary fetch failed or returned null.
function ScoreNum({
  value,
  light,
  format,
}: {
  value: number | null | undefined
  light: Light | null
  format: (v: number) => string
}) {
  if (value == null || !Number.isFinite(value) || light === null) {
    return <span className="text-caption font-mono text-[11px]">—</span>
  }
  const tone =
    light === "green"
      ? "text-green-700 dark:text-green-400"
      : light === "amber"
        ? "text-amber-700 dark:text-amber-400"
        : "text-red-600 dark:text-red-400"
  return (
    <span className={`font-mono text-xs font-semibold tabular-nums ${tone}`}>
      {format(value)}
    </span>
  )
}

// ── Aggregate summary computation ───────────────────────────────────
interface Aggregate {
  avgScore: number | null
  avgMos: number | null
  avgPiotroski: number | null
  avgConfidence: number | null
  moatCounts: { wide: number; narrow: number; none: number }
}

function computeAggregate(summaries: StockSummary[]): Aggregate {
  const mean = (xs: number[]) =>
    xs.length === 0 ? null : xs.reduce((a, b) => a + b, 0) / xs.length

  const scores = summaries
    .map(s => s.score)
    .filter((v): v is number => v != null && Number.isFinite(v))
  // Average the TRUE (Buffett) MoS: prefer buffett_mos_pct if/when backend
  // adds it; otherwise derive from fair_value + current_price.
  const mos = summaries
    .map(s => {
      const bmos = (s as unknown as Record<string, unknown>).buffett_mos_pct
      if (typeof bmos === "number" && Number.isFinite(bmos)) return bmos
      return computeTrueMos(s.fair_value, s.current_price)
    })
    .filter((v): v is number => v != null && Number.isFinite(v))
  const piotroskis = summaries
    .map(s => s.piotroski)
    .filter((v): v is number => v != null && Number.isFinite(v))
  const confidences = summaries
    .map(s => s.confidence)
    .filter((v): v is number => v != null && Number.isFinite(v))

  const moatCounts = { wide: 0, narrow: 0, none: 0 }
  for (const s of summaries) {
    const m = (s.moat || "").toLowerCase()
    if (m === "wide") moatCounts.wide++
    else if (m === "narrow") moatCounts.narrow++
    else moatCounts.none++
  }

  return {
    avgScore: mean(scores),
    avgMos: mean(mos),
    avgPiotroski: mean(piotroskis),
    avgConfidence: mean(confidences),
    moatCounts,
  }
}

// ── Sub-components ──────────────────────────────────────────────────
function AggregateTile({
  label,
  value,
  bandLight,
  showBar = true,
}: {
  label: string
  value: string
  bandLight: Light | null
  showBar?: boolean
}) {
  const barTone =
    bandLight === "green"
      ? "bg-green-500"
      : bandLight === "amber"
        ? "bg-amber-500"
        : bandLight === "red"
          ? "bg-red-500"
          : "bg-border"
  return (
    <div className="flex flex-col gap-1 min-w-0">
      <p className="text-[10px] font-bold uppercase tracking-wider text-caption">
        {label}
      </p>
      <p className="text-base font-mono font-semibold text-ink tabular-nums">
        {value}
      </p>
      {showBar && (
        <div className="h-1 rounded-full bg-border/60 overflow-hidden">
          <div className={`h-full ${barTone}`} style={{ width: bandLight ? "100%" : "0%" }} />
        </div>
      )}
    </div>
  )
}

function MoatDistTile({ counts }: { counts: Aggregate["moatCounts"] }) {
  const total = counts.wide + counts.narrow + counts.none
  const widePct = total === 0 ? 0 : (counts.wide / total) * 100
  const narrowPct = total === 0 ? 0 : (counts.narrow / total) * 100
  const nonePct = total === 0 ? 0 : (counts.none / total) * 100
  return (
    <div className="flex flex-col gap-1 min-w-0">
      <p className="text-[10px] font-bold uppercase tracking-wider text-caption">
        Moat mix
      </p>
      <p className="text-base font-mono font-semibold text-ink tabular-nums">
        {counts.wide}W &middot; {counts.narrow}N &middot; {counts.none}—
      </p>
      <div className="h-1 rounded-full bg-border/60 overflow-hidden flex">
        <div className="h-full bg-green-500" style={{ width: `${widePct}%` }} />
        <div className="h-full bg-amber-500" style={{ width: `${narrowPct}%` }} />
        <div className="h-full bg-red-500" style={{ width: `${nonePct}%` }} />
      </div>
    </div>
  )
}

function Skeleton() {
  return (
    <section
      className="bg-surface border border-border rounded-2xl overflow-hidden"
      data-testid="quality-card-loading-skeleton"
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="h-4 w-56 bg-border rounded animate-pulse" />
        <div className="h-3 w-14 bg-border/70 rounded animate-pulse" />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 px-4 py-3 border-b border-border">
        {[0, 1, 2, 3, 4].map(i => (
          <div key={i} className="flex flex-col gap-1.5">
            <div className="h-2 w-16 bg-border/70 rounded animate-pulse" />
            <div className="h-4 w-12 bg-border rounded animate-pulse" />
            <div className="h-1 w-full bg-border/60 rounded animate-pulse" />
          </div>
        ))}
      </div>
      <div className="divide-y divide-border">
        {[0, 1, 2].map(i => (
          <div key={i} className="flex items-center gap-3 px-4 py-2.5">
            <div className="h-6 w-6 rounded-full bg-border/70 animate-pulse" />
            <div className="h-3 w-16 bg-border rounded animate-pulse" />
            <div className="flex-1" />
            {[0, 1, 2, 3, 4].map(j => (
              <div key={j} className="h-3 w-10 bg-border/70 rounded animate-pulse" />
            ))}
          </div>
        ))}
      </div>
    </section>
  )
}

function EmptyState() {
  return (
    <section
      className="bg-surface border border-border rounded-2xl p-6 text-center"
      data-testid="quality-card-empty"
    >
      <div className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-bg/50 mb-2">
        <BarChart3 className="w-5 h-5 text-caption" aria-hidden />
      </div>
      <h3 className="text-sm font-semibold text-ink mb-1">
        Your portfolio quality posture
      </h3>
      <p className="text-xs text-body mb-4 max-w-md mx-auto">
        Add stocks to your portfolio to see quality signals across your holdings.
      </p>
      <PressScale>
        <Link
          href="/search"
          className="inline-flex items-center gap-1.5 bg-brand text-white text-xs font-semibold px-3 py-1.5 rounded-lg hover:opacity-90 transition"
        >
          Find stocks to add
        </Link>
      </PressScale>
    </section>
  )
}

// ── Main component ─────────────────────────────────────────────────
export default function PortfolioQualityCard() {
  const token = useAuthStore(s => s.token)

  // Step 1 — fetch the user's holdings list. Shares the canonical
  // ["holdings-live"] query key with PortfolioPanel so the two surfaces
  // dedupe into ONE /portfolio/holdings-live request on load (they were
  // previously on separate keys and fired the call twice).
  const { data: holdingsResp, isLoading: holdingsLoading } = useQuery({
    queryKey: ["holdings-live"],
    queryFn: getHoldingsLive,
    enabled: !!token,
    staleTime: 60 * 1000,
    retry: 1,
  })

  // Next.js 16 ships the React Compiler — we leave memoisation to it
  // rather than wrapping each derived value in useMemo. The Compiler
  // sees the dependency graph and produces the same memo'd output.
  const holdings: LiveHolding[] = holdingsResp?.holdings ?? []

  // Step 2 — batch-fetch a StockSummary per ticker via useQueries. One
  // round-trip per holding, but React Query parallelises and the
  // backend response is 6h-cached so this is inexpensive. The display_ticker
  // is the stripped form (no .NS / .BO suffix), matching the
  // /api/v1/public/stock-summary path convention.
  const summaryQueries = useQueries({
    queries: holdings.map(h => ({
      queryKey: ["stock-summary-quality-card", h.display_ticker],
      queryFn: () => getStockSummary(h.display_ticker),
      staleTime: 5 * 60 * 1000,
      retry: 1,
      enabled: !!token,
    })),
  })

  const summariesReady = summaryQueries.every(q => !q.isLoading)

  // Build a parallel array of {holding, summary|null} so render is purely
  // a function of this list — no index juggling later. We deliberately do
  // NOT memoise on `summaryQueries` (each render produces a new array
  // identity from React Query); the cost is one map/filter per render
  // over an array bounded by `holdings.length`, which is small (≤ 8 in
  // the rendered slice).
  type Row = { holding: LiveHolding; summary: StockSummary | null }
  const rows: Row[] = holdings.map((h, i) => ({
    holding: h,
    summary: summaryQueries[i]?.data ?? null,
  }))

  const successSummaries: StockSummary[] = rows
    .map(r => r.summary)
    .filter((s): s is StockSummary => s != null)

  const agg = computeAggregate(successSummaries)

  // Loading: both the holdings fetch AND at least one summary outstanding.
  if (holdingsLoading || (holdings.length > 0 && !summariesReady)) {
    return <Skeleton />
  }
  if (holdings.length === 0) return <EmptyState />

  // Render
  return (
    <section
      className="bg-surface border border-border rounded-2xl overflow-hidden"
      data-testid="quality-card"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-brand" aria-hidden />
          <h3 className="text-sm font-bold uppercase tracking-wider text-ink">
            Your portfolio quality posture
          </h3>
        </div>
        <Link
          href="/portfolio"
          className="text-xs font-semibold text-brand hover:underline"
          data-testid="quality-card-see-all"
        >
          See all →
        </Link>
      </div>

      {/* Aggregate row — 5 mini-stats. Stacks 2x3 below sm. */}
      <div
        className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 px-4 py-3 border-b border-border bg-bg/30"
        data-testid="quality-card-aggregate"
      >
        <AggregateTile
          label="Avg score"
          value={agg.avgScore != null ? `${agg.avgScore.toFixed(0)}/100` : "—"}
          bandLight={scoreLight(agg.avgScore)}
        />
        <AggregateTile
          label="Avg MoS"
          value={
            agg.avgMos != null
              ? (displayMos(agg.avgMos, null, null) ?? "—")
              : "—"
          }
          bandLight={mosLight(agg.avgMos)}
        />
        <AggregateTile
          label="Avg Piotroski"
          value={agg.avgPiotroski != null ? `${agg.avgPiotroski.toFixed(1)}/9` : "—"}
          bandLight={piotroskiLight(agg.avgPiotroski)}
        />
        <AggregateTile
          label="Avg confidence"
          value={agg.avgConfidence != null ? `${agg.avgConfidence.toFixed(0)}%` : "—"}
          bandLight={confidenceLight(agg.avgConfidence)}
        />
        <MoatDistTile counts={agg.moatCounts} />
      </div>

      {/* Per-position rows */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-bg/40 border-b border-border">
            <tr>
              <th className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-wider text-caption">
                Ticker
              </th>
              <th className="px-2 py-2 text-right text-[10px] font-bold uppercase tracking-wider text-caption">
                Score
              </th>
              <th className="px-2 py-2 text-right text-[10px] font-bold uppercase tracking-wider text-caption">
                MoS
              </th>
              <th className="px-2 py-2 text-right text-[10px] font-bold uppercase tracking-wider text-caption hidden sm:table-cell">
                Piotroski
              </th>
              <th className="px-2 py-2 text-right text-[10px] font-bold uppercase tracking-wider text-caption hidden md:table-cell">
                Confidence
              </th>
              <th className="px-2 py-2 text-right text-[10px] font-bold uppercase tracking-wider text-caption hidden md:table-cell">
                Moat
              </th>
              <th className="px-2 py-2 text-right text-[10px] font-bold uppercase tracking-wider text-caption">
                Signals
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 8).map(({ holding, summary }) => {
              const sScore = summary?.score ?? null
              // sUpside = the old "MoS" field — actually implied upside (FV-price)/price
              const sUpside = summary?.mos ?? null
              // sTrueMos = Buffett MoS = (1 - price/FV)*100; same sign as upside
              const sTrueMos: number | null = summary
                ? (() => {
                    const bmos = (summary as unknown as Record<string, unknown>).buffett_mos_pct
                    if (typeof bmos === "number" && Number.isFinite(bmos)) return bmos
                    return computeTrueMos(summary.fair_value, summary.current_price)
                  })()
                : null
              const sPio = summary?.piotroski ?? null
              const sConf = summary?.confidence ?? null
              const sMoat = summary?.moat ?? null
              return (
                <tr
                  key={holding.ticker}
                  className="border-b border-border last:border-b-0 hover:bg-bg/50 transition"
                  data-testid="quality-card-row"
                >
                  <td className="px-3 py-2">
                    <Link
                      href={`/analysis/${holding.display_ticker}`}
                      className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink hover:text-brand"
                      data-testid="quality-card-row-link"
                    >
                      <TickerAvatar
                        ticker={holding.ticker}
                        sector={holding.sector}
                        size="sm"
                      />
                      <span className="font-mono">{holding.display_ticker}</span>
                    </Link>
                  </td>
                  <td className="px-2 py-2 text-right">
                    <ScoreNum
                      value={sScore}
                      light={scoreLight(sScore)}
                      format={v => `${v.toFixed(0)}`}
                    />
                  </td>
                  <td className="px-2 py-2 text-right">
                    {sTrueMos != null ? (
                      <div className="flex flex-col items-end gap-0.5">
                        <ScoreNum
                          value={sTrueMos}
                          light={mosLight(sTrueMos)}
                          format={v => displayMos(v, null, null) ?? "—"}
                        />
                        {sUpside != null && (
                          <span className="text-[10px] text-caption font-mono">
                            {sUpside >= 0 ? "+" : ""}{sUpside.toFixed(1)}% upside
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="text-caption font-mono text-[11px]">—</span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-right hidden sm:table-cell">
                    <ScoreNum
                      value={sPio}
                      light={piotroskiLight(sPio)}
                      format={v => `${v.toFixed(0)}/9`}
                    />
                  </td>
                  <td className="px-2 py-2 text-right hidden md:table-cell">
                    <ScoreNum
                      value={sConf}
                      light={confidenceLight(sConf)}
                      format={v => `${v.toFixed(0)}%`}
                    />
                  </td>
                  <td className="px-2 py-2 text-right hidden md:table-cell">
                    <MoatPill moat={sMoat} />
                  </td>
                  <td className="px-2 py-2 text-right">
                    <TrafficLights score={sScore} mos={sTrueMos} piotroski={sPio} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="px-4 py-2 text-[10px] text-caption border-t border-border">
        Tap any ticker to see the full quality breakdown.
      </div>
    </section>
  )
}
