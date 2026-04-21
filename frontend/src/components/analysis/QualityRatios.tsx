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
    neutral: "border-l-border",
  }[tone]
  const valueClass = {
    green:   "text-green-700",
    amber:   "text-amber-700",
    red:     "text-red-700",
    neutral: "text-caption",
  }[tone]

  return (
    <div
      className={cn(
        "rounded-xl bg-surface border border-border border-l-[3px] p-3",
        toneClass,
      )}
      title={tooltip}
    >
      <p className="text-[10px] text-caption uppercase tracking-wide">{label}</p>
      <p className={cn("text-lg font-bold font-mono tabular-nums mt-0.5", valueClass)}>
        {value}
      </p>
      {subtitle && (
        <p className="text-[10px] text-caption mt-0.5">{subtitle}</p>
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

  const segments: Segment[] = [
    { label: "Promoter", pct: p,             color: "bg-blue-500" },
    { label: "FII",      pct: f ?? 0,        color: "bg-purple-500" },
    { label: "DII",      pct: d ?? 0,        color: "bg-cyan-500" },
    { label: "Public",   pct: pub ?? 0,      color: "bg-border" },
  ]
  const total = segments.reduce((s, x) => s + x.pct, 0)

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
      <div className="grid grid-cols-4 gap-2 text-[10px]">
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
export default function QualityRatios({ quality, insights }: Props) {
  const { roce, debt_ebitda, debt_ebitda_label, interest_coverage } = quality
  const evEbitda = insights.ev_ebitda
  const isBank = quality.is_bank === true

  // If every ratio is null AND no shareholding data, don't render at all —
  // avoids showing an empty shell on tickers with no DB coverage. For
  // banks we include the bank-native metrics in the "anyRatio" check so
  // a bank page with ROA / C/I / YoY but no generic ratios still renders.
  const anyBankMetric =
    [quality.roa, quality.cost_to_income, quality.advances_yoy, quality.deposits_yoy,
     quality.pat_yoy_bank, quality.revenue_yoy_bank].some(v => v !== null && v !== undefined)
  const anyRatio =
    [roce, debt_ebitda, interest_coverage, evEbitda].some(v => v !== null && v !== undefined)
    || anyBankMetric
  const anyShareholding =
    [quality.promoter_pct, quality.fii_pct, quality.dii_pct].some(v => v !== null && v !== undefined)
  if (!anyRatio && !anyShareholding) return null

  return (
    <div className="bg-surface rounded-2xl border border-border p-5 space-y-4">
      <h2 className="text-sm font-semibold text-ink">
        {isBank ? "Bank Ratios" : "Quality Ratios"}
      </h2>

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
              tooltip="Return on Assets. Net income ÷ total assets × 100. The clearest single measure of how profitably a bank runs its balance sheet. Indian bank cohort: >1.4% strong, ~1.0% average, <0.6% weak."
            />
            <RatioCard
              label="ROE"
              value={fmtRatio(quality.roe, "%")}
              tone={quality.roe === null || quality.roe === undefined
                ? "neutral"
                : quality.roe >= 15 ? "green"
                : quality.roe >= 10 ? "amber" : "red"}
              tooltip="Return on Equity. Net income ÷ shareholder equity. Indian private banks target >15%; PSU banks run 12-16%."
            />
            <RatioCard
              label="Cost / Income"
              value={fmtRatio(quality.cost_to_income, "%")}
              tone={costToIncomeTone(quality.cost_to_income)}
              tooltip="Operating expense ÷ total income. Lower is better. Top Indian private banks run ~40-45%; PSU banks ~55-65%."
            />
            <RatioCard
              label="Advances YoY"
              value={fmtRatio(quality.advances_yoy, "%")}
              subtitle="Proxy: total assets YoY"
              tone={growthYoyTone(quality.advances_yoy)}
              tooltip="Loan book year-on-year growth, proxied via total assets (until we wire NSE XBRL Schedule VII). Indian system credit grows ~10-12% long-term."
            />
            <RatioCard
              label="Deposits YoY"
              value={fmtRatio(quality.deposits_yoy, "%")}
              subtitle="Proxy: total liab YoY"
              tone={growthYoyTone(quality.deposits_yoy)}
              tooltip="Deposit base year-on-year growth, proxied via total liabilities (until we wire NSE XBRL Schedule V). Slower than advances signals funding stress."
            />
            <RatioCard
              label="PAT YoY"
              value={fmtRatio(quality.pat_yoy_bank, "%")}
              tone={growthYoyTone(quality.pat_yoy_bank)}
              tooltip="Net profit year-on-year growth."
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
    </div>
  )
}
