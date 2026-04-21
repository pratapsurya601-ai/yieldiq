"use client"

import { useMemo } from "react"
import { cn } from "@/lib/utils"
import { formatCurrency } from "@/lib/utils"
import type { QualityOutput, InsightCards as InsightCardsType, ValuationOutput } from "@/types/api"

interface InsightCardsProps {
  quality: QualityOutput
  insights: InsightCardsType
  valuation: ValuationOutput
  currency?: string
  sector?: string
  ticker?: string
}

interface CardData {
  title: string
  value: string
  subtitle: string
  color: string
  icon: string
  borderColor: string
  subtitleColor?: string
  disabled?: boolean
  tooltip?: string
}

// ── Helpers for the four financial-ratio cards ───────────────
// Centralised so the JSX stays readable and the thresholds match
// the product spec (ROCE / Debt-EBITDA / Interest Coverage bands).
//
// For banks (isBankLike=true), the three leverage/return-on-capital
// cards don't apply — we show a banker's note pointing the user at
// the Prism axis that DOES answer the equivalent question for a
// bank, per feat/bank-prism-metrics (2026-04-21).
function _roceCard(
  roce: number | null | undefined,
  isBankLike: boolean = false,
): CardData {
  if (isBankLike) {
    return {
      title: "ROCE",
      value: "\u2014",
      subtitle: "Not applicable \u2014 banks use capital adequacy, not capital employed. See Safety axis \u2192",
      color: "text-caption",
      icon: "\u{1f4c8}",
      borderColor: "border-l-border",
      disabled: true,
      tooltip: "Return on Capital Employed is a non-financial metric \u2014 capital adequacy (Tier-1 / CAR) is the right safety proxy for a bank.",
    }
  }
  if (roce === null || roce === undefined) {
    return {
      title: "ROCE",
      value: "\u2014",
      subtitle: "Awaiting data \u2014 updates weekly",
      color: "text-caption",
      icon: "\u{1f4c8}",
      borderColor: "border-l-border",
      tooltip: "Return on Capital Employed \u2014 how efficiently the business turns capital into earnings.",
    }
  }
  const band =
    roce > 20 ? { c: "text-green-700", b: "border-l-green-500", label: "Excellent" }
    : roce >= 15 ? { c: "text-blue-700", b: "border-l-blue-500", label: "Healthy" }
    : roce >= 10 ? { c: "text-amber-700", b: "border-l-amber-500", label: "Moderate" }
    : { c: "text-red-700", b: "border-l-red-500", label: "Weak" }
  return {
    title: "ROCE",
    value: `${roce.toFixed(1)}%`,
    subtitle: band.label,
    color: band.c,
    icon: "\u{1f4c8}",
    borderColor: band.b,
    tooltip: "Return on Capital Employed \u2014 how efficiently the business turns capital into earnings.",
  }
}

function _debtEbitdaCard(
  debtEbitda: number | null | undefined,
  label: string | null | undefined,
  isBankLike: boolean,
): CardData {
  if (isBankLike) {
    return {
      title: "Debt / EBITDA",
      value: "\u2014",
      subtitle: "Not applicable \u2014 deposits aren\u2019t debt. See Safety axis \u2192",
      color: "text-caption",
      icon: "\u2696\ufe0f",
      borderColor: "border-l-border",
      disabled: true,
      tooltip: "Debt / EBITDA treats liabilities as borrowings. For a bank, deposits fund the business \u2014 they aren\u2019t debt in the corporate-finance sense.",
    }
  }
  if (debtEbitda === null || debtEbitda === undefined) {
    return {
      title: "Debt / EBITDA",
      value: "\u2014",
      subtitle: "Awaiting data \u2014 updates weekly",
      color: "text-caption",
      icon: "\u2696\ufe0f",
      borderColor: "border-l-border",
      tooltip: "Leverage ratio \u2014 how many years of EBITDA would repay all debt. Banks excluded.",
    }
  }
  const band =
    debtEbitda < 1.0 ? { c: "text-green-700", b: "border-l-green-500", label: "Excellent" }
    : debtEbitda < 2.5 ? { c: "text-blue-700", b: "border-l-blue-500", label: "Healthy" }
    : debtEbitda < 4.0 ? { c: "text-amber-700", b: "border-l-amber-500", label: "Leveraged" }
    : { c: "text-red-700", b: "border-l-red-500", label: "High Risk" }
  return {
    title: "Debt / EBITDA",
    value: `${debtEbitda.toFixed(1)}x`,
    subtitle: label ?? band.label,
    color: band.c,
    icon: "\u2696\ufe0f",
    borderColor: band.b,
    tooltip: "Leverage ratio \u2014 how many years of EBITDA would repay all debt. Banks excluded.",
  }
}

function _interestCoverageCard(
  ic: number | null | undefined,
  isBankLike: boolean,
): CardData {
  if (isBankLike) {
    return {
      title: "Interest Coverage",
      value: "\u2014",
      subtitle: "Not applicable \u2014 for banks, interest is revenue. See Quality axis \u2192",
      color: "text-caption",
      icon: "\u{1f6e1}\ufe0f",
      borderColor: "border-l-border",
      disabled: true,
      tooltip: "Interest Coverage measures how many times operating profit covers interest expense. For a bank, interest earned IS the revenue line \u2014 the ratio is nonsensical.",
    }
  }
  if (ic === null || ic === undefined) {
    return {
      title: "Interest Coverage",
      value: "\u2014",
      subtitle: "Awaiting data \u2014 updates weekly",
      color: "text-caption",
      icon: "\u{1f6e1}\ufe0f",
      borderColor: "border-l-border",
      tooltip: "How many times operating profit covers interest expense. Banks excluded.",
    }
  }
  const band =
    ic > 5 ? { c: "text-green-700", b: "border-l-green-500", label: "Strong" }
    : ic >= 2 ? { c: "text-blue-700", b: "border-l-blue-500", label: "Adequate" }
    : ic >= 1 ? { c: "text-amber-700", b: "border-l-amber-500", label: "Weak" }
    : { c: "text-red-700", b: "border-l-red-500", label: "Distressed" }
  return {
    title: "Interest Coverage",
    value: `${ic.toFixed(1)}x`,
    subtitle: band.label,
    color: band.c,
    icon: "\u{1f6e1}\ufe0f",
    borderColor: band.b,
    tooltip: "How many times operating profit covers interest expense. Banks excluded.",
  }
}

function _promoterCard(
  promoterPct: number | null | undefined,
  pledgePct: number | null | undefined,
): CardData {
  if (promoterPct === null || promoterPct === undefined) {
    return {
      title: "Promoter Holding",
      value: "\u2014",
      subtitle: "Not disclosed",
      color: "text-caption",
      icon: "\u{1f465}",
      borderColor: "border-l-border",
      tooltip: "Percent of shares held by promoters. Higher generally means aligned interests, but watch for pledge.",
    }
  }
  const pledged = pledgePct !== null && pledgePct !== undefined && pledgePct > 0
  const band =
    promoterPct >= 50 ? { c: "text-blue-700", b: "border-l-blue-500", label: "Strong alignment" }
    : promoterPct >= 25 ? { c: "text-body", b: "border-l-border", label: "Moderate" }
    : { c: "text-amber-700", b: "border-l-amber-500", label: "Low stake" }
  const subtitle = pledged
    ? `${band.label} \u00b7 ${pledgePct!.toFixed(1)}% pledged`
    : band.label
  return {
    title: "Promoter Holding",
    value: `${promoterPct.toFixed(1)}%`,
    subtitle,
    subtitleColor: pledged ? "text-red-600" : undefined,
    color: band.c,
    icon: "\u{1f465}",
    borderColor: pledged ? "border-l-red-500" : band.b,
    tooltip: "Percent of shares held by promoters. Higher generally means aligned interests, but watch for pledge.",
  }
}

export default function InsightCards({ quality, insights, valuation, currency = "INR", sector = "", ticker = "" }: InsightCardsProps) {
  // Separate genuine business red flags from model/data warnings
  const MODEL_WARNING_PATTERNS = /missing|using default|estimated|no data|unavailable|not available|insufficient/i
  const businessFlags = (insights.red_flags || []).filter((f) => !MODEL_WARNING_PATTERNS.test(f))
  const modelWarnings = (insights.red_flags || []).filter((f) => MODEL_WARNING_PATTERNS.test(f))

  // Banks / NBFCs — mirror the backend rule so the frontend never
  // promises a computation for tickers the backend deliberately
  // returned None for.
  const _sectorLC = (sector || "").toLowerCase()
  const _tkrUpper = (ticker || "").toUpperCase()
  const isBankLike =
    _sectorLC.includes("bank") ||
    _sectorLC.includes("financial") ||
    _tkrUpper.endsWith("BANK.NS") ||
    _tkrUpper.endsWith("BANK.BO")

  // Prefer the authoritative backend flag (quality.is_bank, 2026-04-21).
  // Fall back to the string heuristic for back-compat with any payload
  // that predates the new field.
  const isBankFromBackend = quality.is_bank === true
  const isBank = isBankFromBackend || isBankLike

  const ratioCards: CardData[] = useMemo(() => [
    _roceCard(quality.roce, isBank),
    _debtEbitdaCard(quality.debt_ebitda, quality.debt_ebitda_label, isBank),
    _interestCoverageCard(quality.interest_coverage, isBank),
    _promoterCard(quality.promoter_pct, quality.promoter_pledge_pct),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [quality.roce, quality.debt_ebitda, quality.debt_ebitda_label, quality.interest_coverage, quality.promoter_pct, quality.promoter_pledge_pct, isBank])

  const cards: CardData[] = useMemo(() => [
    {
      title: "Piotroski F-Score",
      value: `${quality.piotroski_score}/9`,
      subtitle: quality.piotroski_grade,
      color: quality.piotroski_score >= 7 ? "text-blue-700" : quality.piotroski_score >= 4 ? "text-amber-700" : "text-red-700",
      icon: "\u{1f4ca}",
      borderColor: quality.piotroski_score >= 7 ? "border-l-blue-500" : quality.piotroski_score >= 4 ? "border-l-amber-500" : "border-l-red-500",
    },
    {
      title: "Moat",
      value: quality.moat,
      subtitle: `Score: ${quality.moat_score}/100`,
      color: quality.moat === "Wide" ? "text-blue-700" : quality.moat === "Narrow" ? "text-amber-700" : "text-red-700",
      icon: "\u{1f6e1}\ufe0f",
      borderColor: quality.moat === "Wide" ? "border-l-blue-500" : quality.moat === "Narrow" ? "border-l-amber-500" : "border-l-red-500",
    },
    {
      title: "Red Flags",
      value: businessFlags.length === 0 ? "None" : `${businessFlags.length} found`,
      subtitle: businessFlags.length > 0 ? businessFlags[0] : "No concerns detected",
      color: businessFlags.length === 0 ? "text-blue-700" : "text-red-700",
      icon: "\u{1f6a9}",
      borderColor: businessFlags.length === 0 ? "border-l-blue-500" : "border-l-red-500",
    },
    (() => {
      if (insights.earnings_date) {
        const formatted = new Date(insights.earnings_date).toLocaleDateString("en-IN", {
          day: "numeric", month: "short", year: "numeric",
        })
        const daysLabel = insights.earnings_days_until !== null ? ` (in ${insights.earnings_days_until}d)` : ""
        return {
          title: "Earnings",
          value: formatted,
          subtitle: insights.earnings_est_eps !== null
            ? `Est. EPS: ${insights.earnings_est_eps.toFixed(2)}${daysLabel}`
            : `Upcoming earnings${daysLabel}`,
          color: "text-body",
          icon: "\u{1f4c5}",
          borderColor: "border-l-border",
        }
      }
      return {
        title: "Earnings",
        value: "Not scheduled",
        subtitle: "No confirmed earnings date yet",
        color: "text-body",
        icon: "\u{1f4c5}",
        borderColor: "border-l-border",
      }
    })(),
    (() => {
      const div = insights.dividend
      if (div?.has_dividends && div.current_yield_pct !== null && div.current_yield_pct !== undefined) {
        const s = div.sustainability
        const sustLabel = s === "strong" ? "\u25cf Strong"
          : s === "at_risk" ? "\u25cf At Risk"
          : "\u25cf Moderate"
        const sustColor = s === "strong" ? "text-green-600"
          : s === "at_risk" ? "text-red-600"
          : "text-yellow-600"
        const borderColor = s === "strong" ? "border-l-green-500"
          : s === "at_risk" ? "border-l-red-500"
          : "border-l-yellow-500"
        const payoutLabel = div.payout_ratio_pct !== null && div.payout_ratio_pct !== undefined
          ? `${div.payout_ratio_pct.toFixed(0)}%`
          : "\u2014"
        const card: CardData = {
          title: "Dividends",
          value: `${div.current_yield_pct.toFixed(1)}%`,
          subtitle: `${sustLabel} \u00b7 Payout ${payoutLabel}`,
          subtitleColor: sustColor,
          color: "text-body",
          icon: "\u{1f4b0}",
          borderColor,
        }
        return card
      }
      const empty: CardData = {
        title: "Dividends",
        value: "None",
        subtitle: "No dividends paid",
        color: "text-caption",
        icon: "\u{1f4b0}",
        borderColor: "border-l-border",
      }
      return empty
    })(),
    {
      title: "Wall Street Target",
      value: insights.wall_street_avg_target !== null && insights.wall_street_avg_target > 0
        ? formatCurrency(insights.wall_street_avg_target, currency)
        : "No coverage",
      subtitle: insights.wall_street_target_count !== null && insights.wall_street_target_count > 0
        ? `${insights.wall_street_target_count} analyst${insights.wall_street_target_count !== 1 ? "s" : ""}`
        : insights.wall_street_avg_target !== null && insights.wall_street_avg_target > 0
          ? "Analyst consensus"
          : "No analyst coverage",
      color: "text-body",
      icon: "\u{1f3af}",
      borderColor: "border-l-border",
    },
    (() => {
      const deals = insights.bulk_deals ?? []
      const latestDeal = deals.length > 0 ? deals[0] : null
      if (latestDeal) {
        const clientShort = latestDeal.client.length > 20 ? latestDeal.client.slice(0, 18) + "..." : latestDeal.client
        const qtyLabel = latestDeal.qty_lakh >= 1 ? `${latestDeal.qty_lakh.toFixed(1)}L` : `${Math.round(latestDeal.qty_lakh * 1e5).toLocaleString("en-IN")}`
        return {
          title: "Insider Activity",
          value: `${latestDeal.deal_type === "BUY" ? "Buy" : "Sell"} (${latestDeal.category})`,
          subtitle: `${clientShort} ${qtyLabel} @ ${currency === "INR" ? "\u20b9" : "$"}${Math.round(latestDeal.price).toLocaleString(currency === "INR" ? "en-IN" : "en-US")}`,
          color: latestDeal.deal_type === "BUY" ? "text-blue-700" : "text-red-700",
          icon: "\u{1f465}",
          borderColor: latestDeal.deal_type === "BUY" ? "border-l-blue-500" : "border-l-red-500",
        }
      }
      return {
        title: "Insider Activity",
        value: "None",
        subtitle: "No bulk/block deals in 90 days",
        color: "text-body" as const,
        icon: "\u{1f465}",
        borderColor: "border-l-border" as const,
      }
    })(),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [quality, insights, valuation, currency, businessFlags.length])

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {cards.map((card) => (
          <div
            key={card.title}
            className={cn(
              "rounded-xl bg-surface border border-border border-l-[3px] p-4",
              "shadow-sm",
              card.borderColor
            )}
          >
            <div className="flex items-center gap-1.5 mb-1.5">
              <span className="text-sm">{card.icon}</span>
              <p className="text-xs text-caption">{card.title}</p>
            </div>
            <p className={cn("text-lg font-semibold", card.color)}>{card.value}</p>
            <p className={cn("text-xs mt-1 line-clamp-1", card.subtitleColor ?? "text-caption")}>{card.subtitle}</p>
          </div>
        ))}
      </div>

      {/* Financial ratios — kept in a labelled secondary section so
          the primary 7-card grid stays readable on mobile (2 cols)
          rather than spilling into an 11-card tile wall. */}
      <div className="pt-2">
        <p className="text-xs font-semibold text-caption mb-2 px-1">Financial Ratios</p>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {ratioCards.map((card) => (
            <div
              key={card.title}
              title={card.tooltip}
              className={cn(
                "rounded-xl bg-surface border border-border border-l-[3px] p-4 shadow-sm",
                card.borderColor,
                card.disabled && "opacity-60",
              )}
            >
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="text-sm">{card.icon}</span>
                <p className="text-xs text-caption">{card.title}</p>
              </div>
              <p className={cn("text-lg font-semibold", card.color)}>{card.value}</p>
              <p className={cn("text-xs mt-1 line-clamp-1", card.subtitleColor ?? "text-caption")}>{card.subtitle}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Model / Data Warnings — separated from business red flags */}
      {modelWarnings.length > 0 && (
        <div className="rounded-xl bg-amber-50 border border-amber-100 p-4">
          <p className="text-xs font-semibold text-amber-700 mb-2">Data Notes</p>
          <ul className="space-y-1">
            {modelWarnings.map((w, i) => (
              <li key={i} className="text-xs text-amber-600 flex items-start gap-1.5">
                <span className="mt-0.5 flex-shrink-0">&#x26A0;</span>
                <span>{w}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
