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
}

interface CardData {
  title: string
  value: string
  subtitle: string
  color: string
  icon: string
  borderColor: string
  subtitleColor?: string
}

export default function InsightCards({ quality, insights, valuation, currency = "INR" }: InsightCardsProps) {
  // Separate genuine business red flags from model/data warnings
  const MODEL_WARNING_PATTERNS = /missing|using default|estimated|no data|unavailable|not available|insufficient/i
  const businessFlags = (insights.red_flags || []).filter((f) => !MODEL_WARNING_PATTERNS.test(f))
  const modelWarnings = (insights.red_flags || []).filter((f) => MODEL_WARNING_PATTERNS.test(f))

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
          color: "text-gray-700",
          icon: "\u{1f4c5}",
          borderColor: "border-l-gray-300",
        }
      }
      return {
        title: "Earnings",
        value: "N/A",
        subtitle: "No upcoming earnings data",
        color: "text-gray-700",
        icon: "\u{1f4c5}",
        borderColor: "border-l-gray-300",
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
          color: "text-gray-700",
          icon: "\u{1f4b0}",
          borderColor,
        }
        return card
      }
      const empty: CardData = {
        title: "Dividends",
        value: "None",
        subtitle: "No dividends paid",
        color: "text-gray-400",
        icon: "\u{1f4b0}",
        borderColor: "border-l-gray-200",
      }
      return empty
    })(),
    {
      title: "Wall Street Target",
      value: insights.wall_street_avg_target !== null && insights.wall_street_avg_target > 0
        ? formatCurrency(insights.wall_street_avg_target, currency)
        : "N/A",
      subtitle: insights.wall_street_target_count !== null && insights.wall_street_target_count > 0
        ? `${insights.wall_street_target_count} analyst${insights.wall_street_target_count !== 1 ? "s" : ""}`
        : insights.wall_street_avg_target !== null && insights.wall_street_avg_target > 0
          ? "Analyst consensus"
          : "No analyst coverage",
      color: "text-gray-700",
      icon: "\u{1f3af}",
      borderColor: "border-l-gray-300",
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
        color: "text-gray-700" as const,
        icon: "\u{1f465}",
        borderColor: "border-l-gray-300" as const,
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
              "rounded-xl bg-white border border-gray-100 border-l-[3px] p-4",
              "shadow-sm",
              card.borderColor
            )}
          >
            <div className="flex items-center gap-1.5 mb-1.5">
              <span className="text-sm">{card.icon}</span>
              <p className="text-xs text-gray-500">{card.title}</p>
            </div>
            <p className={cn("text-lg font-semibold", card.color)}>{card.value}</p>
            <p className={cn("text-xs mt-1 line-clamp-1", card.subtitleColor ?? "text-gray-400")}>{card.subtitle}</p>
          </div>
        ))}
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
