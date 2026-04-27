"use client"

import { useMemo } from "react"
import { cn } from "@/lib/utils"
import { formatCurrency } from "@/lib/utils"
import type { QualityOutput, InsightCards as InsightCardsType, ValuationOutput } from "@/types/api"
import MetricTooltip from "@/components/analysis/MetricTooltip"
import FreshnessStamp from "@/components/common/FreshnessStamp"

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
  /** Caption-sized attribution line rendered below the subtitle.
   *  Used for third-party data (e.g. analyst consensus from Finnhub)
   *  where SEBI compliance requires we disclose provenance and that
   *  the figure is reference data, not our recommendation. */
  source?: string
  /** feat/freshness-stamps — ISO timestamp for the "As of X" caption
   *  rendered under the source line. Used by the Analyst Consensus
   *  card to tell the user when the target was last refreshed. */
  freshnessAt?: string | null
  /** Prefix for the freshness caption. Defaults to "As of". */
  freshnessPrefix?: string
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
    promoterPct >= 50 ? { c: "text-blue-700", b: "border-l-blue-500", label: "High alignment" }
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
  // structured: non-info = risks; info = strengths. Both counts are surfaced
  // in dedicated summary cards below, derived from the same filtered array
  // so the summary and the Risk & Quality Deep Dive always agree.
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
    (() => {
      // Moat colouring follows the backend label mapping
      // (`_moat_label_from_score` in screener/moat_engine.py):
      //   Wide      → blue   (strong)
      //   Moderate  → green  (good; new band added 2026-04-23)
      //   Narrow    → amber  (acceptable)
      //   None / —  → red    (no durable advantage)
      const m = quality.moat
      const color =
        m === "Wide"     ? "text-blue-700"
        : m === "Moderate" ? "text-green-700"
        : m === "Narrow"   ? "text-amber-700"
        :                    "text-red-700"
      const borderColor =
        m === "Wide"     ? "border-l-blue-500"
        : m === "Moderate" ? "border-l-green-500"
        : m === "Narrow"   ? "border-l-amber-500"
        :                    "border-l-red-500"
      return {
        title: "Moat",
        value: m,
        subtitle: `Score: ${quality.moat_score}/100`,
        color,
        icon: "\u{1f6e1}\ufe0f",
        borderColor,
        metricKey: "moat",
      }
    })(),
    {
      title: "Red Flags",
      value: businessFlags.length === 0 ? "None" : `${businessFlags.length} found`,
      subtitle: businessFlags.length > 0 ? businessFlags[0] : "No concerns detected",
      color: businessFlags.length === 0 ? "text-blue-700" : "text-red-700",
      icon: "\u{1f6a9}",
      borderColor: businessFlags.length === 0 ? "border-l-blue-500" : "border-l-red-500",
    },
    // Strengths summary card — single-source-of-truth is the same
    // `red_flags_structured` array the Risk & Quality Deep Dive reads
    // (via RedFlagInsights). Prior to 2026-04-23 this count wasn't
    // surfaced here; the summary card and deep-dive disagreed on
    // TITAN ("0 strengths" vs "3 strengths"). Deriving from the
    // exact same filter makes them provably identical. See PR
    // `fix/moat-floor-strength-ssot`.
    (() => {
      const strengthTitles = structured
        .filter((f) => f.severity === "info")
        .map((f) => f.title)
      const n = strengthTitles.length
      return {
        title: "Strengths",
        value: n === 0 ? "None" : `${n} found`,
        subtitle: n > 0 ? strengthTitles[0] : "No positive signals detected",
        color: n > 0 ? "text-green-700" : "text-caption",
        icon: "\u2728",
        borderColor: n > 0 ? "border-l-green-500" : "border-l-border",
      }
    })(),
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
      // fix/data-quality-gate (2026-04-27): a 0.0% current yield is not
      // a "Moderate" dividend \u2014 it is the absence of one. Likewise a
      // last_ex_date older than 24 months means the company has stopped
      // paying, regardless of whether the historical sustainability tag
      // still says "moderate". In both cases we collapse the card to a
      // "No recent dividends" state so the compact summary cannot
      // contradict the expanded DividendTracker below it.
      const div = insights.dividend
      const TWENTY_FOUR_MONTHS_MS = 24 * 30 * 24 * 60 * 60 * 1000
      const lastEx = div?.last_ex_date ? new Date(div.last_ex_date) : null
      const lastExValid = lastEx !== null && Number.isFinite(lastEx.getTime())
      const isStale =
        lastExValid && (Date.now() - (lastEx as Date).getTime()) > TWENTY_FOUR_MONTHS_MS
      const yieldNum =
        div?.current_yield_pct !== null && div?.current_yield_pct !== undefined
          ? div.current_yield_pct
          : null
      const hasLiveYield = yieldNum !== null && yieldNum > 0 && !isStale
      if (div?.has_dividends && hasLiveYield) {
        const s = div.sustainability
        const sustLabel = s === "strong" ? "\u25cf High"
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
          value: `${(yieldNum as number).toFixed(1)}%`,
          subtitle: `${sustLabel} \u00b7 Payout ${payoutLabel}`,
          subtitleColor: sustColor,
          color: "text-body",
          icon: "\u{1f4b0}",
          borderColor,
        }
        return card
      }
      // Stale schedule branch: keep the historical context (last paid
      // date) instead of pretending no dividend ever existed.
      if (div?.has_dividends && isStale) {
        const fmt = (lastEx as Date).toLocaleDateString("en-IN", {
          month: "short", year: "numeric",
        })
        const lapsed: CardData = {
          title: "Dividends",
          value: "Lapsed",
          subtitle: `No recent dividends (last paid ${fmt})`,
          color: "text-caption",
          icon: "\u{1f4b0}",
          borderColor: "border-l-border",
        }
        return lapsed
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
      // FIX-SEBI-COMPLIANCE (2026-04-23, Gap 3): renamed from
      // "Wall Street Target" -> "Analyst Consensus (third-party)".
      // The old label implied a YieldIQ-produced price target, which
      // we do not publish. This number is the mean of external sell-
      // side analyst targets sourced from Finnhub (see backend
      // services/analysis/service.py :: finnhub_price_target). The
      // card now also surfaces the provenance caption so the user
      // understands it is reference data, not our recommendation.
      title: "Analyst Consensus (third-party)",
      value: insights.wall_street_avg_target !== null && insights.wall_street_avg_target > 0
        ? formatCurrency(insights.wall_street_avg_target, currency)
        : "No coverage",
      subtitle: insights.wall_street_target_count !== null && insights.wall_street_target_count > 0
        ? `${insights.wall_street_target_count} analyst${insights.wall_street_target_count !== 1 ? "s" : ""}`
        : insights.wall_street_avg_target !== null && insights.wall_street_avg_target > 0
          ? "Analyst consensus"
          : "No analyst coverage",
      source: "Source: Finnhub \u2014 reference data only, not investment advice.",
      // feat/freshness-stamps: tell the user how fresh the consensus
      // number is. Backend stamps with compute time whenever any
      // target data is present; null → stamp is omitted entirely.
      freshnessAt: insights.analyst_target_as_of ?? null,
      freshnessPrefix: "As of",
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
            {card.source ? (
              <p className="text-caption text-[11px] mt-1 leading-snug">{card.source}</p>
            ) : null}
            {card.freshnessAt ? (
              <FreshnessStamp
                timestamp={card.freshnessAt}
                prefix={card.freshnessPrefix ?? "As of"}
                className="block mt-0.5"
              />
            ) : null}
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
        <div className="rounded-xl bg-amber-50 border border-amber-100 dark:bg-amber-950/30 dark:border-amber-900 p-4">
          <p className="text-xs font-semibold text-amber-700 dark:text-amber-300 mb-2">Data Notes</p>
          <ul className="space-y-1">
            {modelWarnings.map((w, i) => (
              <li key={i} className="text-xs text-amber-600 dark:text-amber-400 flex items-start gap-1.5">
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
