"use client"

import { useMemo, useState } from "react"
import { cn } from "@/lib/utils"
import FreshnessStamp from "@/components/common/FreshnessStamp"
import type { DividendData } from "@/types/api"

interface Props {
  dividend?: DividendData | null
  currency?: string
}

function currencySymbol(c: string): string {
  return c === "INR" ? "\u20b9" : "$"
}

const SUST_CARD: Record<string, string> = {
  strong: "bg-green-50 text-green-700 border border-green-200",
  moderate: "bg-yellow-50 text-yellow-700 border border-yellow-200",
  at_risk: "bg-red-50 text-red-700 border border-red-200",
}

const SUST_LABEL: Record<string, string> = {
  strong: "● HIGH",
  moderate: "● MODERATE",
  at_risk: "● AT RISK",
}

function fmtCoverage(v: number | null): string {
  if (v === null || v === undefined) return "—"
  if (v >= 2) return `${v.toFixed(1)}× ✓`
  if (v >= 1) return `${v.toFixed(1)}× ⚠`
  return `${v.toFixed(1)}× ✗`
}

export default function DividendTracker({ dividend, currency = "INR" }: Props) {
  const [expanded, setExpanded] = useState(false)
  const sym = currencySymbol(currency)

  const maxBar = useMemo(() => {
    if (!dividend?.fy_history?.length) return 0
    return Math.max(...dividend.fy_history.map(f => f.total_per_share))
  }, [dividend])

  // Nothing to render — compact InsightCards card shows "None" for us
  if (!dividend || !dividend.has_dividends) return null

  const summaryLine = (() => {
    const parts: string[] = []
    if (dividend.dividend_rate_per_share) {
      parts.push(`${sym}${dividend.dividend_rate_per_share.toFixed(2)}/share`)
    }
    if (dividend.current_yield_pct !== null && dividend.current_yield_pct !== undefined) {
      parts.push(`${dividend.current_yield_pct.toFixed(1)}% yield`)
    }
    if (dividend.consecutive_years > 0) {
      parts.push(
        `${dividend.consecutive_years} consecutive year${dividend.consecutive_years === 1 ? "" : "s"}`
      )
    }
    return parts.join(" · ") || "Dividend history available"
  })()

  return (
    <div className="bg-surface rounded-2xl border border-border overflow-hidden">
      {/* Header / collapsed state */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between p-4 hover:bg-bg transition-colors text-left"
        aria-expanded={expanded}
      >
        <div>
          <p className="text-sm font-semibold text-ink">💰 Dividend History</p>
          <p className="text-xs text-caption mt-0.5">{summaryLine}</p>
          {/* feat/freshness-stamps: most recent ex-date anchors the
              card so a lapsed dividend schedule is immediately visible. */}
          <FreshnessStamp
            timestamp={dividend.last_ex_date}
            prefix="Last dividend"
            className="mt-0.5 block"
          />
        </div>
        <span
          className={cn(
            "text-caption text-sm transition-transform duration-200",
            expanded && "rotate-180"
          )}
          aria-hidden="true"
        >
          ▼
        </span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t border-border space-y-4">
          {/* Key metrics grid */}
          <div className="grid grid-cols-2 gap-2 pt-2">
            <div className="rounded-xl bg-bg p-3">
              <p className="text-[11px] text-caption uppercase tracking-wide">Current Yield</p>
              <p className="text-lg font-semibold text-ink mt-0.5">
                {dividend.current_yield_pct !== null && dividend.current_yield_pct !== undefined
                  ? `${dividend.current_yield_pct.toFixed(1)}%`
                  : "—"}
              </p>
            </div>
            <div className="rounded-xl bg-bg p-3">
              <p className="text-[11px] text-caption uppercase tracking-wide">5Y Avg Yield</p>
              <p className="text-lg font-semibold text-ink mt-0.5">
                {dividend.five_yr_avg_yield !== null && dividend.five_yr_avg_yield !== undefined
                  ? `${dividend.five_yr_avg_yield.toFixed(1)}%`
                  : "—"}
              </p>
            </div>
            <div className="rounded-xl bg-bg p-3">
              <p className="text-[11px] text-caption uppercase tracking-wide">Payout Ratio</p>
              <p className="text-lg font-semibold text-ink mt-0.5">
                {dividend.payout_ratio_pct !== null && dividend.payout_ratio_pct !== undefined
                  ? `${dividend.payout_ratio_pct.toFixed(0)}%`
                  : "—"}
              </p>
            </div>
            <div className="rounded-xl bg-bg p-3">
              <p className="text-[11px] text-caption uppercase tracking-wide">FCF Coverage</p>
              <p className="text-lg font-semibold text-ink mt-0.5">
                {fmtCoverage(dividend.coverage_ratio)}
              </p>
            </div>
          </div>

          {/* Sustainability */}
          <div
            className={cn(
              "rounded-xl p-3 space-y-1",
              SUST_CARD[dividend.sustainability] ?? SUST_CARD.moderate,
            )}
          >
            <p className="text-[11px] font-bold uppercase tracking-wide">
              {SUST_LABEL[dividend.sustainability] ?? "● —"}
            </p>
            {dividend.sustainability_reason && (
              <p className="text-xs leading-relaxed">{dividend.sustainability_reason}</p>
            )}
          </div>

          {/* FY history bars */}
          {dividend.fy_history.length > 0 && (
            <div className="space-y-2">
              <p className="text-[11px] font-semibold text-caption uppercase tracking-wide">
                {sym} per share by financial year
              </p>
              <div className="space-y-1.5">
                {dividend.fy_history.map(item => {
                  const pct = maxBar > 0 ? (item.total_per_share / maxBar) * 100 : 0
                  return (
                    <div key={item.fy} className="flex items-center gap-2 text-xs">
                      <span className="w-14 text-caption tabular-nums">{item.fy}</span>
                      <div className="flex-1 h-5 bg-bg rounded relative overflow-hidden">
                        <div
                          className="h-full bg-blue-400 rounded"
                          style={{ width: `${Math.max(4, pct * 0.6)}%` }}
                        />
                      </div>
                      <span className="w-16 text-right text-ink font-medium tabular-nums">
                        {sym}{item.total_per_share.toFixed(2)}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Next ex-date */}
          {dividend.next_ex_date && (
            <div className="rounded-xl bg-blue-50 border border-blue-100 p-3">
              <p className="text-[11px] font-semibold text-blue-700 uppercase tracking-wide mb-0.5">
                📅 Next Ex-Dividend Date
              </p>
              <p className="text-sm text-blue-900">
                {new Date(dividend.next_ex_date).toLocaleDateString("en-IN", {
                  day: "numeric", month: "short", year: "numeric",
                })}
                {dividend.next_ex_days !== null && dividend.next_ex_days !== undefined && (
                  <span className="text-blue-700">
                    {" "}
                    (in {dividend.next_ex_days} day{dividend.next_ex_days === 1 ? "" : "s"})
                  </span>
                )}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
