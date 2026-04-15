"use client"

import type { QualityOutput, InsightCards as InsightCardsType } from "@/types/api"
import { cn } from "@/lib/utils"

interface Props {
  quality: QualityOutput
  insights: InsightCardsType
}

/* ------------------------------------------------------------------ */
/* Tiny card primitive                                                  */
/* ------------------------------------------------------------------ */
function RatioCard({
  label,
  value,
  subtitle,
  tone,
  tooltip,
}: {
  label: string
  value: string
  subtitle?: string
  tone: "green" | "amber" | "red" | "neutral"
  tooltip: string
}) {
  const toneClass = {
    green:   "border-l-green-500",
    amber:   "border-l-amber-500",
    red:     "border-l-red-500",
    neutral: "border-l-gray-200",
  }[tone]
  const valueClass = {
    green:   "text-green-700",
    amber:   "text-amber-700",
    red:     "text-red-700",
    neutral: "text-gray-400",
  }[tone]

  return (
    <div
      className={cn(
        "rounded-xl bg-white border border-gray-100 border-l-[3px] p-3",
        toneClass,
      )}
      title={tooltip}
    >
      <p className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</p>
      <p className={cn("text-lg font-bold font-mono tabular-nums mt-0.5", valueClass)}>
        {value}
      </p>
      {subtitle && (
        <p className="text-[10px] text-gray-400 mt-0.5">{subtitle}</p>
      )}
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

function fmtRatio(v: number | null | undefined, suffix: string): string {
  if (v === null || v === undefined) return "—"
  return `${v.toFixed(1)}${suffix}`
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
      <p className="text-xs text-gray-400 text-center py-4">
        Shareholding data not available
      </p>
    )
  }

  const segments: Segment[] = [
    { label: "Promoter", pct: p,             color: "bg-blue-500" },
    { label: "FII",      pct: f ?? 0,        color: "bg-purple-500" },
    { label: "DII",      pct: d ?? 0,        color: "bg-cyan-500" },
    { label: "Public",   pct: pub ?? 0,      color: "bg-gray-300" },
  ]
  const total = segments.reduce((s, x) => s + x.pct, 0)

  return (
    <div className="space-y-2">
      {/* Stacked bar */}
      <div className="flex h-2.5 rounded-full overflow-hidden bg-gray-100">
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
      <div className="grid grid-cols-4 gap-2 text-[10px]">
        {segments.map(seg => (
          <div key={seg.label} className="flex items-center gap-1">
            <span className={cn("h-2 w-2 rounded-full", seg.color)} aria-hidden />
            <span className="text-gray-500">{seg.label}</span>
            <span className="ml-auto font-medium text-gray-900 tabular-nums">
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
            : "text-gray-500",
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
export default function QualityRatios({ quality, insights }: Props) {
  const { roce, debt_ebitda, debt_ebitda_label, interest_coverage } = quality
  const evEbitda = insights.ev_ebitda

  // If every ratio is null AND no shareholding data, don't render at all —
  // avoids showing an empty shell on tickers with no DB coverage.
  const anyRatio =
    [roce, debt_ebitda, interest_coverage, evEbitda].some(v => v !== null && v !== undefined)
  const anyShareholding =
    [quality.promoter_pct, quality.fii_pct, quality.dii_pct].some(v => v !== null && v !== undefined)
  if (!anyRatio && !anyShareholding) return null

  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-5 space-y-4">
      <h2 className="text-sm font-semibold text-gray-900">Quality Ratios</h2>

      {/* 2x2 grid of ratio cards */}
      <div className="grid grid-cols-2 gap-2">
        <RatioCard
          label="ROCE"
          value={fmtRatio(roce, "%")}
          tone={roceTone(roce)}
          tooltip="Return on Capital Employed. EBIT ÷ total assets × 100. Measures how efficiently the business uses its capital base. Higher is better."
        />
        <RatioCard
          label="EV / EBITDA"
          value={fmtRatio(evEbitda, "x")}
          tone={evEbitdaTone(evEbitda)}
          tooltip="Enterprise Value ÷ EBITDA. A capital-structure-neutral valuation multiple — better than P/E for debt-heavy businesses. Lower is cheaper."
        />
        <RatioCard
          label="Debt / EBITDA"
          value={fmtRatio(debt_ebitda, "x")}
          subtitle={debt_ebitda_label ?? undefined}
          tone={debtEbitdaTone(debt_ebitda)}
          tooltip="Years of EBITDA needed to pay off debt. <1 excellent, 1–3 healthy, 3–5 leveraged, >5 risky."
        />
        <RatioCard
          label="Int. Coverage"
          value={fmtRatio(interest_coverage, "x")}
          tone={interestCoverageTone(interest_coverage)}
          tooltip="EBIT ÷ Interest Expense. How many times operating profit covers interest payments. >3 is safe."
        />
      </div>

      {/* Shareholding breakdown */}
      {anyShareholding && (
        <div className="pt-3 border-t border-gray-100 space-y-2">
          <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
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
    </div>
  )
}
