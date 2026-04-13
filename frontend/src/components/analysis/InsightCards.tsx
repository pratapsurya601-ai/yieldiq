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
}

export default function InsightCards({ quality, insights, valuation, currency = "INR" }: InsightCardsProps) {
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
      value: insights.red_flag_count === 0 ? "None" : `${insights.red_flag_count} found`,
      subtitle: insights.red_flags.length > 0 ? insights.red_flags[0] : "No concerns detected",
      color: insights.red_flag_count === 0 ? "text-blue-700" : "text-red-700",
      icon: "\u{1f6a9}",
      borderColor: insights.red_flag_count === 0 ? "border-l-blue-500" : "border-l-red-500",
    },
    {
      title: "Earnings",
      value: insights.earnings_days_until !== null ? `${insights.earnings_days_until}d` : "N/A",
      subtitle: insights.earnings_est_eps !== null
        ? `Est. EPS: ${insights.earnings_est_eps.toFixed(2)}`
        : "No upcoming earnings data",
      color: "text-gray-700",
      icon: "\u{1f4c5}",
      borderColor: "border-l-gray-300",
    },
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
    {
      title: "Insider Activity",
      value: insights.insider_net_sentiment ?? "N/A",
      subtitle: "Recent insider transactions",
      color: insights.insider_net_sentiment === "Positive"
        ? "text-blue-700"
        : insights.insider_net_sentiment === "Negative"
          ? "text-red-700"
          : "text-gray-700",
      icon: "\u{1f465}",
      borderColor: insights.insider_net_sentiment === "Positive"
        ? "border-l-blue-500"
        : insights.insider_net_sentiment === "Negative"
          ? "border-l-red-500"
          : "border-l-gray-300",
    },
  ], [quality, insights, valuation, currency])

  return (
    <div className="grid grid-cols-2 gap-3">
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
          <p className="text-xs text-gray-400 mt-1 line-clamp-1">{card.subtitle}</p>
        </div>
      ))}
    </div>
  )
}
