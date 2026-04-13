"use client"

import { cn } from "@/lib/utils"
import { formatCurrency } from "@/lib/utils"
import type { QualityOutput, InsightCards as InsightCardsType, ValuationOutput } from "@/types/api"

interface InsightCardsProps {
  quality: QualityOutput
  insights: InsightCardsType
  valuation: ValuationOutput
}

interface CardData {
  title: string
  value: string
  subtitle: string
  color: string
}

export default function InsightCards({ quality, insights, valuation }: InsightCardsProps) {
  const cards: CardData[] = [
    {
      title: "Piotroski F-Score",
      value: `${quality.piotroski_score}/9`,
      subtitle: quality.piotroski_grade,
      color: quality.piotroski_score >= 7 ? "text-blue-700" : quality.piotroski_score >= 4 ? "text-amber-700" : "text-red-700",
    },
    {
      title: "Moat",
      value: quality.moat,
      subtitle: `Score: ${quality.moat_score}/100`,
      color: quality.moat === "Wide" ? "text-blue-700" : quality.moat === "Narrow" ? "text-amber-700" : "text-red-700",
    },
    {
      title: "Red Flags",
      value: insights.red_flag_count === 0 ? "None" : `${insights.red_flag_count} found`,
      subtitle: insights.red_flags.length > 0 ? insights.red_flags[0] : "No concerns detected",
      color: insights.red_flag_count === 0 ? "text-blue-700" : "text-red-700",
    },
    {
      title: "Earnings",
      value: insights.earnings_days_until !== null ? `${insights.earnings_days_until}d` : "N/A",
      subtitle: insights.earnings_est_eps !== null
        ? `Est. EPS: ${insights.earnings_est_eps.toFixed(2)}`
        : "No upcoming earnings data",
      color: "text-gray-700",
    },
    {
      title: "Wall Street Target",
      value: insights.wall_street_avg_target !== null
        ? formatCurrency(insights.wall_street_avg_target, valuation.current_price > 10000 ? "INR" : "USD")
        : "N/A",
      subtitle: insights.wall_street_target_count !== null
        ? `${insights.wall_street_target_count} analyst${insights.wall_street_target_count !== 1 ? "s" : ""}`
        : "No analyst coverage",
      color: "text-gray-700",
    },
    {
      title: "Insider Activity",
      value: insights.insider_net_sentiment ?? "N/A",
      subtitle: "Recent insider transactions",
      color: insights.insider_net_sentiment === "Positive"
        ? "text-blue-700"
        : insights.insider_net_sentiment === "Negative"
          ? "text-red-700"
          : "text-gray-700",
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-3">
      {cards.map((card) => (
        <div
          key={card.title}
          className={cn(
            "rounded-xl bg-white border border-gray-100 p-3",
            "shadow-sm"
          )}
        >
          <p className="text-xs text-gray-500 mb-1">{card.title}</p>
          <p className={cn("text-lg font-semibold", card.color)}>{card.value}</p>
          <p className="text-xs text-gray-400 mt-0.5 line-clamp-1">{card.subtitle}</p>
        </div>
      ))}
    </div>
  )
}
