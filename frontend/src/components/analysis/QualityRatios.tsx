"use client"

import { useState, useMemo } from "react"
import type { QualityOutput, InsightCards as InsightCardsType } from "@/types/api"
import type { RatioHistoryResponse, RatioHistoryPeriod } from "@/lib/api"
import { cn } from "@/lib/utils"
import MetricTooltip from "@/components/analysis/MetricTooltip"
import FreshnessStamp from "@/components/common/FreshnessStamp"
import Sparkline, { type SparklinePoint } from "@/components/analysis/Sparkline"
import RatioTrendModal, { type RatioTrendSeriesPoint } from "@/components/analysis/RatioTrendModal"

interface Props {
  quality: QualityOutput
  insights: InsightCardsType
  /** Optional 10-year ratio history; when absent, cards render without sparklines (graceful). */
  ratioHistory?: RatioHistoryResponse | null
}

/* ------------------------------------------------------------------ */
/* Trend helpers — turn RatioHistoryResponse → per-metric time series  */
/* ------------------------------------------------------------------ */
/** Key on RatioHistoryPeriod → trend series (oldest→newest). */
function buildSeries(
  data: RatioHistoryResponse | null | undefined,
  key: keyof RatioHistoryPeriod,
): RatioTrendSeriesPoint[] {
  if (!data || !data.periods || data.periods.length === 0) return []
  // Endpoint returns newest→oldest; reverse for chart rendering.
  const sorted = [...data.periods].sort((a, b) => {
    const ax = a.period_end || ""
    const bx = b.period_end || ""
    return ax.localeCompare(bx)
  })
  const windowed = sorted.slice(-10)
  return windowed.map(p => {
    const raw = p[key]
    const v = typeof raw === "number" && !isNaN(raw) ? raw : null
    return { period_end: p.period_end || "", value: v }
  })
}

function seriesToPoints(series: RatioTrendSeriesPoint[]): SparklinePoint[] {
  return series.map(p => (p.value === null ? null : p.value))
}

/* ------------------------------------------------------------------ */
/* Tiny card primitive                                                  */
/* ------------------------------------------------------------------ */
function RatioCard({
  label,
  value,
  subtitle,
  tone,
  metricKey,
  sparklinePoints,
  onExpand,
}: {
  label: string
  value: string
  subtitle?: string
  tone: "green" | "amber" | "red" | "neutral"
  /** Dictionary key for the MetricTooltip popover. */
  metricKey: string
  /** Optional trend values (oldest→newest); when ≥2 numeric values, renders sparkline. */
  sparklinePoints?: SparklinePoint[]
  /** If provided, card becomes clickable and opens the expanded trend modal. */
  onExpand?: () => void
}) {
  const toneClass = {
    green:   "border-l-green-500",
    amber:   "border-l-amber-500",
    red:     "border-l-red-500",
    neutral: "border-l-border",
  }[tone]
  const valueClass = {
    green:   "text-green-700",
    amber:   "text-amber-700",
    red:     "text-red-700",
    neutral: "text-caption",
  }[tone]

  let numericCount = 0
  if (sparklinePoints) {
    for (const p of sparklinePoints) {
      if (typeof p === "number" && !isNaN(p)) numericCount++
    }
  }
  const hasTrend = numericCount >= 2
  const clickable = hasTrend && !!onExpand

  const body = (
    <>
      <MetricTooltip metricKey={metricKey}>
        <p className="text-[10px] text-caption uppercase tracking-wide">{label}</p>
      </MetricTooltip>
      <p className={cn("text-lg font-bold font-mono tabular-nums mt-0.5", valueClass)}>
        {value}
      </p>
      {subtitle && (
        <p className="text-[10px] text-caption mt-0.5">{subtitle}</p>
      )}
      {hasTrend && (
        <div className="mt-2">
          <Sparkline
            points={sparklinePoints!}
            color={tone}
            height={32}
            ariaLabel={`${label} 10-year trend`}
          />
        </div>
      )}
    </>
  )

  if (clickable) {
    return (
      <button
        type="button"
        onClick={onExpand}
        className={cn(
          "text-left w-full rounded-xl bg-surface border border-border border-l-[3px] p-3",
          "hover:border-ink/20 hover:shadow-sm transition focus:outline-none",
          "focus-visible:ring-2 focus-visible:ring-ink/20",
          toneClass,
        )}
        aria-label={`${label} — open trend chart`}
      >
        {body}
      </button>
    )
  }

  return (
    <div
      className={cn(
        "rounded-xl bg-surface border border-border border-l-[3px] p-3",
        toneClass,
      )}
    >
      {body}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Tone helpers                                                         */
/* ------------------------------------------------------------------ */
function roceTone(v: number | null | undefined): "green" | "amber" | "red" | "neutral" {
  if (v === null || v === undefined) return "neutral"
  if (v >= 15) return "green"
  if (v >= 10) return "amber"
  return "red"
}
function evEbitdaTone(v: number | null | undefined): "green" | "amber" | "red" | "neutral" {
  if (v === null || v === undefined || v <= 0) return "neutral"
  if (v < 15) return "green"
  if (v < 25) return "amber"
  return "red"
}
function debtEbitdaTone(v: number | null | undefined): "green" | "amber" | "red" | "neutral" {
  if (v === null || v === undefined) return "neutral"
  if (v < 1) return "green"
  if (v < 3) return "amber"
  return "red"
}
function interestCoverageTone(v: number | null | undefined): "green" | "amber" | "red" | "neutral" {
  if (v === null || v === undefined) return "neutral"
  if (v > 5) return "green"
  if (v >= 2) return "amber"
  return "red"
}

/* Phase 2.1 — tone helpers for Day-3 #12 ratio backfill. */
function currentRatioTone(v: number | null | undefined): "green" | "amber" | "red" | "neutral" {
  if (v === null || v === undefined) return "neutral"
  // >1.5 comfortable short-term liquidity; 1.0-1.5 adequate; <1 potential squeeze
  if (v >= 1.5) return "green"
  if (v >= 1.0) return "amber"
  return "red"
}
function assetTurnoverTone(v: number | null | undefined): "green" | "amber" | "red" | "neutral" {
  if (v === null || v === undefined) return "neutral"
  // Broad industrial benchmark: >1 strong capital efficiency, 0.5-1 average, <0.5 capital heavy
  if (v >= 1.0) return "green"
  if (v >= 0.5) return "amber"
  return "red"
}
function revenueCagrTone(v: number | null | undefined): "green" | "amber" | "red" | "neutral" {
  // v is a DECIMAL (0.124 = 12.4%). Indian blue-chip cohort: >15% strong, 8-15% average, <8% weak.
  if (v === null || v === undefined) return "neutral"
  const pct = v * 100
  if (pct >= 15) return "green"
  if (pct >= 8) return "amber"
  return "red"
}

function fmtRatio(v: number | null | undefined, suffix: string): string {
  if (v === null || v === undefined) return "—"
  return `${v.toFixed(1)}${suffix}`
}

/* Revenue CAGR is a DECIMAL — convert to percent for display.
   toFixed already preserves the minus sign for negative growth. */
function fmtCagr(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—"
  return `${(v * 100).toFixed(1)}%`
}

/* ------------------------------------------------------------------ */
/* Bank-specific tone helpers                                           */
/* ------------------------------------------------------------------ */
function roaTone(v: number | null | undefined): "green" | "amber" | "red" | "neutral" {
  if (v === null || v === undefined) return "neutral"
  // Indian bank cohort: >1.4% strong, ~1.0% average, <0.6% weak.
  if (v >= 1.4) return "green"
  if (v >= 0.8) return "amber"
  return "red"
}
function costToIncomeTone(v: number | null | undefined): "green" | "amber" | "red" | "neutral" {
  if (v === null || v === undefined) return "neutral"
  // Top private banks 40-45%; PSU 55-65%; struggling >70%.
  if (v <= 50) return "green"
  if (v <= 65) return "amber"
  return "red"
}
function growthYoyTone(v: number | null | undefined): "green" | "amber" | "red" | "neutral" {
  if (v === null || v === undefined) return "neutral"
  if (v >= 12) return "green"
  if (v >= 6) return "amber"
  return "red"
}

/* ------------------------------------------------------------------ */
/* Shareholding stacked bar                                             */
/* ------------------------------------------------------------------ */
interface Segment {
  label: string
  pct: number
  color: string
}

function ShareholdingBar({
  promoter,
  fii,
  dii,
  publicPct,
  pledgePct,
}: {
  promoter: number | null | undefined
  fii: number | null | undefined
  dii: number | null | undefined
  publicPct: number | null | undefined
  pledgePct: number | null | undefined
}) {
  // Use server-provided public_pct when present; fall back to remainder
  // of the other three. Clamp individual values to sane range.
  const clamp = (v: number | null | undefined): number | null =>
    v === null || v === undefined || isNaN(v) ? null : Math.max(0, Math.min(100, v))
  const p = clamp(promoter)
  const f = clamp(fii)
  const d = clamp(dii)
  let pub = clamp(publicPct)
  if (pub === null && p !== null) {
    pub = Math.max(0, 100 - p - (f ?? 0) - (d ?? 0))
  }

  // Not enough data to draw anything useful
  if (p === null) {
    return (
      <p className="text-xs text-caption text-center py-4">
        Shareholding data not available
      </p>
    )
  }

  // Only include FII / DII rows when the server actually reported a
  // value. Defaulting missing fields to 0 renders as "FII 0.0%" which
  // reads as "no foreign holders" — misleading for blue-chips where
  // the data just wasn't wired through. Hide instead of faking.
  const segments: Segment[] = [
    { label: "Promoter", pct: p,             color: "bg-blue-500" },
    ...(f !== null ? [{ label: "FII",    pct: f,       color: "bg-purple-500" }] : []),
    ...(d !== null ? [{ label: "DII",    pct: d,       color: "bg-cyan-500" }]   : []),
    { label: "Public",   pct: pub ?? 0,      color: "bg-border" },
  ]
  const total = segments.reduce((s, x) => s + x.pct, 0)
  const legendCols = segments.length === 4 ? "grid-cols-4"
                    : segments.length === 3 ? "grid-cols-3"
                    : "grid-cols-2"

  return (
    <div className="space-y-2">
      {/* Stacked bar */}
      <div className="flex h-2.5 rounded-full overflow-hidden bg-bg">
        {segments.map(seg => seg.pct > 0 && (
          <div
            key={seg.label}
            className={seg.color}
            style={{ width: `${total > 0 ? (seg.pct / total) * 100 : 0}%` }}
            title={`${seg.label}: ${seg.pct.toFixed(1)}%`}
          />
        ))}
      </div>

      {/* Legend */}
      <div className={cn("grid gap-2 text-[10px]", legendCols)}>
        {segments.map(seg => (
          <div key={seg.label} className="flex items-center gap-1">
            <span className={cn("h-2 w-2 rounded-full", seg.color)} aria-hidden />
            <span className="text-caption">{seg.label}</span>
            <span className="ml-auto font-medium text-ink tabular-nums">
              {seg.pct.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>

      {/* Pledge badge — shown only when > 0 */}
      {pledgePct !== null && pledgePct !== undefined && pledgePct > 0 && (
        <p
          className={cn(
            "text-[11px] font-medium",
            pledgePct > 25 ? "text-red-600"
            : pledgePct > 10 ? "text-amber-700"
            : "text-caption",
          )}
        >
          Promoter pledge: {pledgePct.toFixed(1)}% of holding
        </p>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Main component                                                       */
/* ------------------------------------------------------------------ */
export default function QualityRatios({ quality, insights, ratioHistory }: Props) {
  const { roce, debt_ebitda, debt_ebitda_label, interest_coverage } = quality
  // Phase 2.1 additions — backend already emits these in QualityOutput but
  // they were previously dropped from the render list. Day-3 fix #12.
  const currentRatio = quality.current_ratio
  const assetTurnover = quality.asset_turnover
  const revenueCagr3y = quality.revenue_cagr_3y
  const evEbitda = insights.ev_ebitda
  const isBank = quality.is_bank === true

  // ─── Ratio trends ───────────────────────────────────────────────────
  // Pull each series out of the 10-yr ratio history once per render so
  // sparklines and modals share the same array identity.
  const trends = useMemo(() => ({
    roe: buildSeries(ratioHistory, "roe"),
    roce: buildSeries(ratioHistory, "roce"),
    de_ratio: buildSeries(ratioHistory, "de_ratio"),
    debt_ebitda: buildSeries(ratioHistory, "debt_ebitda"),
    interest_cov: buildSeries(ratioHistory, "interest_cov"),
    pe_ratio: buildSeries(ratioHistory, "pe_ratio"),
    pb_ratio: buildSeries(ratioHistory, "pb_ratio"),
    ev_ebitda: buildSeries(ratioHistory, "ev_ebitda"),
    current_ratio: buildSeries(ratioHistory, "current_ratio"),
    asset_turnover: buildSeries(ratioHistory, "asset_turnover"),
    revenue_yoy: buildSeries(ratioHistory, "revenue_yoy"),
    roa: buildSeries(ratioHistory, "roa"),
  }), [ratioHistory])

  // Expanded-chart modal state — single modal, driven by which ratio is open.
  type OpenRatio =
    | { key: string; title: string; suffix: string; decimals: number
        series: RatioTrendSeriesPoint[]; color: "green" | "amber" | "red" | "neutral"
        threshold?: number }
    | null
  const [openRatio, setOpenRatio] = useState<OpenRatio>(null)

  // If every ratio is null AND no shareholding data, don't render at all —
  // avoids showing an empty shell on tickers with no DB coverage. For
  // banks we include the bank-native metrics in the "anyRatio" check so
  // a bank page with ROA / C/I / YoY but no generic ratios still renders.
  const anyBankMetric =
    [quality.roa, quality.cost_to_income, quality.advances_yoy, quality.deposits_yoy,
     quality.pat_yoy_bank, quality.revenue_yoy_bank].some(v => v !== null && v !== undefined)
  const anyRatio =
    [roce, debt_ebitda, interest_coverage, evEbitda,
     currentRatio, assetTurnover, revenueCagr3y].some(v => v !== null && v !== undefined)
    || anyBankMetric
  const anyShareholding =
    [quality.promoter_pct, quality.fii_pct, quality.dii_pct].some(v => v !== null && v !== undefined)
  if (!anyRatio && !anyShareholding) return null

  // fix/data-quality-gate (2026-04-27): when two or more of the four
  // headline non-bank ratios are unreported the score card and ratio
  // grid both render plausibly but are computed from a thin slice of
  // data. Surface a discreet caption so the user reads the rest of
  // the section in the right confidence band. Banks have their own
  // "Why no ROCE / Debt-EBITDA / Int. Coverage" note already, so we
  // only show this on the generic path.
  const missingCoreCount = isBank
    ? 0
    : [roce, quality.roe, interest_coverage, currentRatio]
        .filter(v => v === null || v === undefined).length
  const limitedFinancialData = missingCoreCount >= 2

  return (
    <div className="bg-surface rounded-2xl border border-border p-5 space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">
          {isBank ? "Bank Ratios" : "Quality Ratios"}
        </h2>
        {/* feat/freshness-stamps: "Latest filing: Mar 2024" tells the
            user whether these ratios are from a recent FY filing or a
            stale row. Null timestamp collapses to nothing. */}
        <FreshnessStamp
          timestamp={quality.latest_filing_period_end}
          prefix="Latest filing"
        />
      </div>

      {limitedFinancialData && (
        <p
          className="text-[11px] text-caption leading-snug"
          aria-label="Limited financial data warning"
        >
          Limited financial data — {missingCoreCount} of ROCE, ROE,
          Interest Coverage, Current Ratio unreported. Score and ratios
          below are computed from a partial filing set.
        </p>
      )}

      {/* Render bank-native cards for banks; generic cards otherwise.
          The generic set (ROCE / Debt/EBITDA / Int Coverage) does not
          apply to deposit-funded businesses, so we replace them with
          ROA / Cost-to-Income / Advances YoY / Deposits YoY and point
          the user at the relevant Prism axis for the numbers that
          DO apply to banks (e.g. capital adequacy → Safety axis). */}
      {isBank ? (
        <>
          <div className="grid grid-cols-2 gap-2">
            <RatioCard
              label="ROA"
              value={fmtRatio(quality.roa, "%")}
              tone={roaTone(quality.roa)}
              metricKey="roa"
              sparklinePoints={seriesToPoints(trends.roa)}
              onExpand={() => setOpenRatio({
                key: "roa", title: "ROA \u2014 10-year trend",
                suffix: "%", decimals: 2,
                series: trends.roa, color: roaTone(quality.roa), threshold: 1.0,
              })}
            />
            <RatioCard
              label="ROE"
              value={fmtRatio(quality.roe, "%")}
              tone={quality.roe === null || quality.roe === undefined
                ? "neutral"
                : quality.roe >= 15 ? "green"
                : quality.roe >= 10 ? "amber" : "red"}
              metricKey="roe"
              sparklinePoints={seriesToPoints(trends.roe)}
              onExpand={() => {
                const tone: "green" | "amber" | "red" | "neutral" =
                  quality.roe === null || quality.roe === undefined
                    ? "neutral"
                    : quality.roe >= 15 ? "green"
                    : quality.roe >= 10 ? "amber" : "red"
                setOpenRatio({
                  key: "roe", title: "ROE \u2014 10-year trend",
                  suffix: "%", decimals: 1,
                  series: trends.roe, color: tone, threshold: 15,
                })
              }}
            />
            <RatioCard
              label="Cost / Income"
              value={fmtRatio(quality.cost_to_income, "%")}
              tone={costToIncomeTone(quality.cost_to_income)}
              metricKey="cost_to_income"
            />
            <RatioCard
              label="Advances YoY"
              value={fmtRatio(quality.advances_yoy, "%")}
              subtitle="Proxy: total assets YoY"
              tone={growthYoyTone(quality.advances_yoy)}
              metricKey="advances_yoy"
            />
            <RatioCard
              label="Deposits YoY"
              value={fmtRatio(quality.deposits_yoy, "%")}
              subtitle="Proxy: total liab YoY"
              tone={growthYoyTone(quality.deposits_yoy)}
              metricKey="deposits_yoy"
            />
            <RatioCard
              label="PAT YoY"
              value={fmtRatio(quality.pat_yoy_bank, "%")}
              tone={growthYoyTone(quality.pat_yoy_bank)}
              metricKey="pat_yoy_bank"
            />
          </div>

          {/* Banker's note: explain why the generic ratios are absent
              and point the user at the Prism axes that DO answer the
              equivalent question for a bank. */}
          <div className="pt-3 border-t border-border space-y-1.5">
            <p className="text-[11px] font-semibold text-caption uppercase tracking-wide">
              Why no ROCE / Debt-EBITDA / Interest Coverage?
            </p>
            <ul className="text-[11px] text-caption space-y-1 leading-relaxed">
              <li>
                <span className="font-medium text-ink">ROCE</span> — not applicable:
                banks use capital adequacy, not capital employed. See Safety axis in
                the Prism.
              </li>
              <li>
                <span className="font-medium text-ink">Debt / EBITDA</span> — not
                applicable: deposits aren&apos;t debt. See Safety axis in the Prism.
              </li>
              <li>
                <span className="font-medium text-ink">Interest Coverage</span> — not
                applicable: for a bank, interest is revenue. See Quality axis in the
                Prism.
              </li>
            </ul>
          </div>
        </>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <RatioCard
            label="ROCE"
            value={fmtRatio(roce, "%")}
            tone={roceTone(roce)}
            metricKey="roce"
            sparklinePoints={seriesToPoints(trends.roce)}
            onExpand={() => setOpenRatio({
              key: "roce", title: "ROCE \u2014 10-year trend",
              suffix: "%", decimals: 1,
              series: trends.roce, color: roceTone(roce), threshold: 15,
            })}
          />
          <RatioCard
            label="EV / EBITDA"
            value={fmtRatio(evEbitda, "x")}
            tone={evEbitdaTone(evEbitda)}
            metricKey="ev_ebitda"
            sparklinePoints={seriesToPoints(trends.ev_ebitda)}
            onExpand={() => setOpenRatio({
              key: "ev_ebitda", title: "EV / EBITDA \u2014 10-year trend",
              suffix: "x", decimals: 1,
              series: trends.ev_ebitda, color: evEbitdaTone(evEbitda),
            })}
          />
          <RatioCard
            label="Debt / EBITDA"
            value={fmtRatio(debt_ebitda, "x")}
            subtitle={debt_ebitda_label ?? undefined}
            tone={debtEbitdaTone(debt_ebitda)}
            metricKey="debt_ebitda"
            sparklinePoints={seriesToPoints(trends.debt_ebitda)}
            onExpand={() => setOpenRatio({
              key: "debt_ebitda", title: "Debt / EBITDA \u2014 10-year trend",
              suffix: "x", decimals: 2,
              series: trends.debt_ebitda, color: debtEbitdaTone(debt_ebitda),
            })}
          />
          <RatioCard
            label="Int. Coverage"
            value={fmtRatio(interest_coverage, "x")}
            tone={interestCoverageTone(interest_coverage)}
            metricKey="interest_coverage"
            sparklinePoints={seriesToPoints(trends.interest_cov)}
            onExpand={() => setOpenRatio({
              key: "interest_cov", title: "Interest Coverage \u2014 10-year trend",
              suffix: "x", decimals: 1,
              series: trends.interest_cov, color: interestCoverageTone(interest_coverage),
              threshold: 2,
            })}
          />
          {/* Phase 2.1 ratios — Day-3 fix #12 (2026-04-22). Backend already
              emits current_ratio / asset_turnover / revenue_cagr_3y in
              QualityOutput; they were silently dropped by the prior render
              list. Revenue CAGR arrives as a DECIMAL, not a percent. */}
          <RatioCard
            label="Current Ratio"
            value={fmtRatio(currentRatio, "x")}
            subtitle="Short-term liquidity"
            tone={currentRatioTone(currentRatio)}
            metricKey="current_ratio"
            sparklinePoints={seriesToPoints(trends.current_ratio)}
            onExpand={() => setOpenRatio({
              key: "current_ratio", title: "Current Ratio \u2014 10-year trend",
              suffix: "x", decimals: 2,
              series: trends.current_ratio, color: currentRatioTone(currentRatio),
              threshold: 1.5,
            })}
          />
          <RatioCard
            label="Asset Turnover"
            value={fmtRatio(assetTurnover, "x")}
            subtitle="Revenue per \u20b9 of assets"
            tone={assetTurnoverTone(assetTurnover)}
            metricKey="asset_turnover"
            sparklinePoints={seriesToPoints(trends.asset_turnover)}
            onExpand={() => setOpenRatio({
              key: "asset_turnover", title: "Asset Turnover \u2014 10-year trend",
              suffix: "x", decimals: 2,
              series: trends.asset_turnover, color: assetTurnoverTone(assetTurnover),
            })}
          />
          <RatioCard
            label="Revenue CAGR (3Y)"
            value={fmtCagr(revenueCagr3y)}
            subtitle="3-year revenue growth"
            tone={revenueCagrTone(revenueCagr3y)}
            metricKey="revenue_cagr_3y"
          />
        </div>
      )}

      {/* Shareholding breakdown */}
      {anyShareholding && (
        <div className="pt-3 border-t border-border space-y-2">
          <p className="text-[11px] font-semibold text-caption uppercase tracking-wide">
            Shareholding
          </p>
          <ShareholdingBar
            promoter={quality.promoter_pct}
            fii={quality.fii_pct}
            dii={quality.dii_pct}
            publicPct={quality.public_pct}
            pledgePct={quality.promoter_pledge_pct}
          />
        </div>
      )}

      {/* Expanded trend chart — only mounted when a ratio card is clicked. */}
      {openRatio && (
        <RatioTrendModal
          open={true}
          onClose={() => setOpenRatio(null)}
          title={openRatio.title}
          suffix={openRatio.suffix}
          decimals={openRatio.decimals}
          series={openRatio.series}
          color={openRatio.color}
          threshold={openRatio.threshold}
        />
      )}
    </div>
  )
}
