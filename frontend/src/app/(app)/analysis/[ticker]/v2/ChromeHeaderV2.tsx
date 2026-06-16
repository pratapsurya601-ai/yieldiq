"use client"

// v2 · Chrome — ticker identity band + quick-stats + provenance bar.
//
// PORTED from the locked demo (app/demo/analysis-redesign/ChromeHeader.tsx)
// but fed REAL props off the AnalysisResponse payload. The demo's
// 52-week dumbbell is OMITTED here: 52-wk hi/lo + Beta are not on the
// analysis payload, so rendering them would require fabricated values.
// (Documented gap — see the PR notes / report.)
import type { AnalysisResponse } from "@/types/api"
import TickerAvatar from "@/components/common/TickerAvatar"
import { formatCurrency, formatRelativeTime } from "@/lib/utils"

import { DEMO_COLORS } from "@/app/demo/analysis-redesign/theme"
import { Muted } from "@/app/demo/analysis-redesign/ui"

/** A single quick-stat tile. `null` value renders a graceful em-dash. */
interface QuickStat {
  label: string
  value: string | null
}

/** Clean a ticker for display (strip exchange suffixes). */
function displayTicker(t: string): string {
  return t.replace(".NS", "").replace(".BO", "").replace(".BSE", "").replace(".NSE", "")
}

/** Format a market cap given in absolute INR into a "₹X.X lakh cr" / "₹X cr" label. */
function marketCapLabel(marketCapInr: number | null | undefined): string | null {
  if (!marketCapInr || !(marketCapInr > 0) || !Number.isFinite(marketCapInr)) return null
  const cr = marketCapInr / 1e7
  if (cr >= 1e5) return `₹${(cr / 1e5).toFixed(2)} lakh cr`
  if (cr >= 1) return `₹${cr.toLocaleString("en-IN", { maximumFractionDigits: 0 })} cr`
  return `₹${(cr).toFixed(2)} cr`
}

/** A pct value (already a percent, e.g. 16.1) → "16.1%" or null. */
function pctOrNull(v: number | null | undefined): string | null {
  if (v == null || !Number.isFinite(v)) return null
  return `${v.toFixed(1)}%`
}

/** A bare ratio (e.g. 18.5) → "18.5" or null. */
function ratioOrNull(v: number | null | undefined): string | null {
  if (v == null || !Number.isFinite(v) || v <= 0) return null
  return v.toFixed(1)
}

export default function ChromeHeaderV2({ data }: { data: AnalysisResponse }) {
  const { company, valuation, quality } = data
  const ticker = displayTicker(company.ticker || data.ticker)
  const exchange = (company.exchange || "").toUpperCase() || null
  const price = valuation.current_price

  // Sub-line: industry · sector. Both nullable on the payload.
  const subBits = [company.industry, company.sector].filter(Boolean) as string[]

  // Quick-stats — REAL payload fields only. P/E and P/B are not first-
  // class on the analysis payload; we omit them gracefully (the strip
  // simply renders fewer tiles) rather than fabricate. ROE / Div yield /
  // ROA come straight off quality + insights.dividend.
  const stats: QuickStat[] = [
    { label: "ROE", value: pctOrNull(quality.roe) },
    { label: "Div yield", value: pctOrNull(data.insights.dividend?.current_yield_pct ?? null) },
    { label: "ROA", value: pctOrNull(quality.roa) },
    // ROCE is on the payload too — a useful 4th tile to keep the grid full.
    { label: "ROCE", value: pctOrNull(quality.roce) },
  ].filter((s) => s.value !== null)

  const mcap = marketCapLabel(company.market_cap)

  // Provenance bar — REAL timestamps off the payload. Each chip self-
  // hides when its source field is absent.
  const filingPeriod = quality.latest_filing_period_end || null
  const fvComputedAt = valuation.fair_value_computed_at || null
  const priceAsOf = valuation.as_of || valuation.current_price_as_of || null

  return (
    <div>
      {/* Identity band */}
      <div className="flex flex-wrap items-center gap-3.5 px-1 pb-4 pt-0.5">
        <TickerAvatar
          ticker={company.ticker || data.ticker}
          size="lg"
          sector={company.sector}
          className="rounded-lg"
        />
        <div className="min-w-[200px] flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[20px] font-medium tracking-tight text-ink">
              {company.company_name || ticker}
            </span>
            <span className="rounded-md border border-border px-1.5 py-0.5 text-[11px] text-caption">
              {exchange ? `${ticker} · ${exchange}` : ticker}
            </span>
          </div>
          {subBits.length > 0 && <Muted className="mt-0.5">{subBits.join(" · ")}</Muted>}
        </div>
        <div className="text-right">
          <div className="num text-[22px] font-medium text-ink">
            <span
              className="v2-live-pulse mr-1.5 inline-block h-[7px] w-[7px] rounded-full align-middle"
              style={{ background: DEMO_COLORS.teal }}
              aria-hidden="true"
            />
            {price > 0 ? formatCurrency(price, company.currency, company.ticker) : "—"}
          </div>
          {mcap && <Muted>Market cap {mcap}</Muted>}
        </div>
      </div>

      {/* Quick-stats strip — scannable factual header. Renders only the
          tiles whose value is real; never a fabricated number. */}
      {stats.length > 0 && (
        <div
          className={`mb-3 grid gap-px overflow-hidden rounded-xl border border-border/70 bg-border/70 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_20px_-12px_rgba(15,23,42,0.10)] ${
            stats.length >= 4 ? "grid-cols-2 sm:grid-cols-4" : "grid-cols-2 sm:grid-cols-3"
          }`}
        >
          {stats.map((s) => (
            <div key={s.label} className="bg-raised px-3 py-2.5 transition-colors hover:bg-surface">
              <div className="text-[10.5px] text-caption">{s.label}</div>
              <div className="num mt-px text-[15.5px] font-semibold text-ink">{s.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Provenance bar — trust at a glance, REAL timestamps. */}
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-xl border border-border/60 bg-raised px-3.5 py-2 text-[12px] text-caption shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_20px_-12px_rgba(15,23,42,0.10)]">
        <span>
          <Dot color={DEMO_COLORS.teal} pulse />
          {priceAsOf ? `Price ${formatRelativeTime(priceAsOf)}` : "Price delayed"}
          {exchange ? ` · ${exchange}` : ""}
        </span>
        {filingPeriod && (
          <span>
            <Dot color={DEMO_COLORS.blue} />
            Financials · filing {filingPeriod}
          </span>
        )}
        {fvComputedAt && (
          <span>
            <Dot color={DEMO_COLORS.purple} />
            Model updated {formatRelativeTime(fvComputedAt)}
          </span>
        )}
        {data.timestamp && (
          <span className="ml-auto">Computed {formatRelativeTime(data.timestamp)}</span>
        )}
      </div>
    </div>
  )
}

function Dot({ color, pulse = false }: { color: string; pulse?: boolean }) {
  return (
    <span
      className={`mr-1.5 inline-block h-2 w-2 rounded-full align-[-1px] ${pulse ? "v2-live-pulse" : ""}`}
      style={{ background: color }}
      aria-hidden="true"
    />
  )
}
