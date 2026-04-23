"use client"

import { useMemo } from "react"
import { cn } from "@/lib/utils"
import { formatCurrency } from "@/lib/utils"
import type { QualityOutput, InsightCards as InsightCardsType, ValuationOutput } from "@/types/api"
import MetricTooltip from "@/components/analysis/MetricTooltip"

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
  /** Key into metric_explanations.ts — drives the hover tooltip. */
  metricKey?: string
}

// ── Helpers for the financial-ratio cards ────────────────────
// NOTE (2026-04-22, fix/day2-stockdetail): ROCE / Debt-EBITDA /
// Interest Coverage cards used to live here too. They duplicated
// the same three ratios in QualityRatios.tsx (Quality tab), so
// users saw each metric twice on every stock page. The generic
// set is now owned solely by QualityRatios; InsightCards keeps
// only the promoter card because it frames ownership/alignment,
// not a "quality ratio".
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
      metricKey: "promoter_holding",
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
    metricKey: "promoter_holding",
  }
}

export default function InsightCards({ quality, insights, valuation, currency = "INR" }: InsightCardsProps) {
  // Single source of truth: red_flags_structured (backend-authored, severity-tagged).
  // Prior to 2026-04-23 this card read the legacy insights.red_flags string list,
  // which left it out of sync with RedFlagInsights (which always used structured).
  // Observed on TITAN.NS: deep-dive said "1 risk · 3 strengths" but this card said
  // "Red Flags: None" — same page, two different answers. Fixed by deriving from
  // structured: non-info = risks; info = strengths (tracked for parity but not
  // surfaced in the card title).
  const MODEL_WARNING_PATTERNS = /missing|using default|estimated|no data|unavailable|not available|insufficient/i
  const structured = insights.red_flags_structured || []
  const businessFlagTitles = structured
    .filter((f) => f.severity !== "info" && !MODEL_WARNING_PATTERNS.test(f.title))
    .map((f) => f.title)
  const businessFlags = businessFlagTitles
  // Preserve the legacy string list for "data limitations" fallback rendering
  // below — that block intentionally surfaces model-level caveats that never
  // made it into the structured list.
  const modelWarnings = (insights.red_flags || []).filter((f) => MODEL_WARNING_PATTERNS.test(f))

  // Secondary "Ownership" strip — the ROCE / Debt-EBITDA / Interest
  // Coverage cards that used to live beside this one were removed
  // on 2026-04-22 because they duplicated QualityRatios exactly.
  const ratioCards: CardData[] = useMemo(() => [
    _promoterCard(quality.promoter_pct, quality.promoter_pledge_pct),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [quality.promoter_pct, quality.promoter_pledge_pct])

  const cards: CardData[] = useMemo(() => [
    {
      title: "Piotroski F-Score",
      value: `${quality.piotroski_score}/9`,
      subtitle: quality.piotroski_grade,
      color: quality.piotroski_score >= 7 ? "text-blue-700" : quality.piotroski_score >= 4 ? "text-amber-700" : "text-red-700",
      icon: "\u{1f4ca}",
      borderColor: quality.piotroski_score >= 7 ? "border-l-blue-500" : quality.piotroski_score >= 4 ? "border-l-amber-500" : "border-l-red-500",
      metricKey: "piotroski_score",
    },
    {
      title: "Moat",
      value: quality.moat,
      subtitle: `Score: ${quality.moat_score}/100`,
      color: quality.moat === "Wide" ? "text-blue-700" : quality.moat === "Narrow" ? "text-amber-700" : "text-red-700",
      icon: "\u{1f6e1}\ufe0f",
      borderColor: quality.moat === "Wide" ? "border-l-blue-500" : quality.moat === "Narrow" ? "border-l-amber-500" : "border-l-red-500",
      metricKey: "moat",
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
          // SEBI-safe framing: the bare word "Buy"/"Sell" as a label can
          // read like a recommendation. This is actually the transaction
          // direction of a publicly-disclosed bulk deal — prefix with
          // "Deal:" so it's unambiguously reporting someone else's trade,
          // not advising the user to do the same.
          value: `Deal: ${latestDeal.deal_type === "BUY" ? "Buy-side" : "Sell-side"} (${latestDeal.category})`,
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
              {card.metricKey ? (
                <MetricTooltip metricKey={card.metricKey}>
                  <p className="text-xs text-caption">{card.title}</p>
                </MetricTooltip>
              ) : (
                <p className="text-xs text-caption">{card.title}</p>
              )}
            </div>
            <p className={cn("text-lg font-semibold", card.color)}>{card.value}</p>
            <p className={cn("text-xs mt-1 line-clamp-1", card.subtitleColor ?? "text-caption")}>{card.subtitle}</p>
          </div>
        ))}
      </div>

      {/* Ownership — secondary strip. Originally held the four
          "financial ratios" (ROCE / Debt-EBITDA / Interest Coverage
          / Promoter) but the first three were deduped into
          QualityRatios on 2026-04-22; only ownership remains here. */}
      <div className="pt-2">
        <p className="text-xs font-semibold text-caption mb-2 px-1">Ownership</p>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {ratioCards.map((card) => (
            <div
              key={card.title}
              className={cn(
                "rounded-xl bg-surface border border-border border-l-[3px] p-4 shadow-sm",
                card.borderColor,
                card.disabled && "opacity-60",
              )}
            >
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="text-sm">{card.icon}</span>
                {card.metricKey ? (
                  <MetricTooltip metricKey={card.metricKey}>
                    <p className="text-xs text-caption">{card.title}</p>
                  </MetricTooltip>
                ) : (
                  <p className="text-xs text-caption">{card.title}</p>
                )}
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
