"use client"

import { useMemo } from "react"
import { cn } from "@/lib/utils"
import { formatCurrency } from "@/lib/utils"
import { currencySymbol, currencyLocale } from "@/lib/currency"
import { metricTone, metricToneTextClass } from "@/lib/metricTone"
import type {
  QualityOutput,
  InsightCards as InsightCardsType,
  ValuationOutput,
  AnalystConsensus,
} from "@/types/api"
import MetricTooltip from "@/components/analysis/MetricTooltip"
import FreshnessStamp from "@/components/common/FreshnessStamp"

interface InsightCardsProps {
  quality: QualityOutput
  insights: InsightCardsType
  valuation: ValuationOutput
  currency?: string | null
  sector?: string
  ticker?: string
  /**
   * Finnhub analyst consensus block (additive, optional). When
   * `coverage_count > 0` the component renders a dedicated
   * <AnalystConsensusPanel> below the card grid AND a richer
   * summary inside the existing "Analyst Consensus (third-party)"
   * card. When null/undefined OR `coverage_count == 0` the card
   * collapses to a small italic "No coverage" line — matching the
   * legacy behavior so older cached payloads keep rendering.
   */
  analystConsensus?: AnalystConsensus | null
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

// ── YieldIQ vs Street agreement classifier ──────────────────
// Sprint A3 (2026-06-09): single source of truth for the
// "We agree with the Street within +/- X%" copy rendered both on
// the compact analyst card and on the larger AnalystConsensusPanel.
// Three observation bands, factual framings only:
//   - aligned  (< 5% gap)   -> "We agree with the Street within +/- 5%."
//   - moderate (5-15% gap)  -> "Our model points X% above/below the Street consensus."
//   - diverge  (>= 15% gap) -> "Our model diverges X% from the Street -- see Reverse-DCF for the implied growth gap."
// All copy is SEBI-safe by construction: no buy/sell/hold/recommend,
// no should/appears/concern, no above/below as a verdict (only as a
// directional descriptor of the model's number vs an observed third-
// party number, which is reporting not advice).
export type AgreementBand = "aligned" | "moderate" | "diverge"
export interface Agreement {
  band: AgreementBand
  /** absolute percentage gap, e.g. 12.4 for 12.4% */
  gapPct: number
  /** signed direction relative to the Street: +X% means YieldIQ > Street */
  signedPct: number
  /** Short one-liner suitable for a compact card subtitle. */
  short: string
  /** Longer prose suitable for the larger AnalystConsensusPanel. */
  long: string
}
export function classifyAgreement(
  ourFv: number | null | undefined,
  street: number | null | undefined,
): Agreement | null {
  if (ourFv === null || ourFv === undefined || !Number.isFinite(ourFv) || ourFv <= 0) return null
  if (street === null || street === undefined || !Number.isFinite(street) || street <= 0) return null
  const signed = ((ourFv - street) / street) * 100
  const gap = Math.abs(signed)
  const dir = signed >= 0 ? "above" : "below"
  if (gap < 5) {
    return {
      band: "aligned",
      gapPct: gap,
      signedPct: signed,
      short: "We agree with the Street within +/- 5%.",
      long: "Our model points within +/- 5% of the Street consensus -- the two valuations corroborate one another.",
    }
  }
  if (gap < 15) {
    return {
      band: "moderate",
      gapPct: gap,
      signedPct: signed,
      short: `Our model points ${gap.toFixed(1)}% ${dir} the Street.`,
      long: `Our model points ${gap.toFixed(1)}% ${dir} the Street consensus. See Reverse-DCF to dial in your own growth assumption and reconcile the gap.`,
    }
  }
  return {
    band: "diverge",
    gapPct: gap,
    signedPct: signed,
    short: `Our model diverges ${gap.toFixed(1)}% from the Street.`,
    long: `Our model diverges ${gap.toFixed(1)}% from the Street consensus. See Reverse-DCF for the implied growth gap that would close it.`,
  }
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
  holdingType?: string | null,
  entity?: string | null,
): CardData {
  // RBI norms: private banks legitimately have no designated promoter.
  // Render the dedicated "No promoter (RBI norms)" tag so HDFCBANK /
  // ICICIBANK / AXISBANK don't keep surfacing as "0.0% \u2014 Low stake".
  if (holdingType === "no_promoter_bank") {
    return {
      title: "Promoter Holding",
      value: "n/a",
      subtitle: "No promoter (RBI norms)",
      color: "text-body",
      icon: "\u{1f3db}\ufe0f",
      borderColor: "border-l-border",
      tooltip: "RBI norms forbid a designated promoter for private commercial banks. Diversified institutional ownership is the structural norm, not a governance gap.",
      metricKey: "promoter_holding",
    }
  }
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
  // Override-aware label. Foreign and govt promoters can be perfectly
  // healthy at any percentage band; the alignment-vs-stake heuristic
  // only applies to ordinary domestic promoter holdings.
  let label: string
  let colorClass: string
  let borderClass: string
  if (holdingType === "foreign_promoter") {
    label = entity ? `Foreign promoter \u00b7 ${entity}` : "Foreign promoter"
    colorClass = "text-tone-info-fg"
    borderClass = "border-l-blue-500"
  } else if (holdingType === "govt_promoter") {
    label = entity ? `Govt promoter \u00b7 ${entity}` : "Govt promoter"
    colorClass = "text-tone-info-fg"
    borderClass = "border-l-blue-500"
  } else {
    const band =
      promoterPct >= 50 ? { c: "text-tone-info-fg", b: "border-l-blue-500", label: "High alignment" }
      : promoterPct >= 25 ? { c: "text-body", b: "border-l-border", label: "Moderate" }
      : { c: "text-tone-warn-fg", b: "border-l-amber-500", label: "Low stake" }
    label = band.label
    colorClass = band.c
    borderClass = band.b
  }
  const subtitle = pledged
    ? `${label} \u00b7 ${pledgePct!.toFixed(1)}% pledged`
    : label
  return {
    title: "Promoter Holding",
    value: `${promoterPct.toFixed(1)}%`,
    subtitle,
    subtitleColor: pledged ? "text-red-600" : undefined,
    color: colorClass,
    icon: "\u{1f465}",
    borderColor: pledged ? "border-l-red-500" : borderClass,
    tooltip: "Percent of shares held by promoters. Higher generally means aligned interests, but watch for pledge.",
    metricKey: "promoter_holding",
  }
}

export default function InsightCards({ quality, insights, valuation, currency, ticker, analystConsensus }: InsightCardsProps) {
  const hasCoverage = !!analystConsensus && analystConsensus.coverage_count > 0
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
    _promoterCard(
      quality.promoter_pct,
      quality.promoter_pledge_pct,
      quality.promoter_holding_type,
      quality.promoter_entity,
    ),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [
    quality.promoter_pct,
    quality.promoter_pledge_pct,
    quality.promoter_holding_type,
    quality.promoter_entity,
  ])

  const cards: CardData[] = useMemo(() => ([
    (() => {
      // Tickertape trick #4 (.audit/tickertape-deep-walk-2026-05-27.md): route
      // F-Score color through the canonical metricTone helper so the band
      // (good/neutral/warn/bad) matches every other metric on the page. The
      // border still uses the legacy color palette so the visual cascade —
      // border-left + value-color — feels consistent with the other tiles.
      const fs = quality.piotroski_score
      const tone = metricTone({ metric: "fscore", value: fs })
      const borderColor =
        tone === "good"    ? "border-l-green-500"
        : tone === "warn"  ? "border-l-amber-500"
        : tone === "bad"   ? "border-l-red-500"
        :                    "border-l-border"
      return {
        title: "Piotroski F-Score",
        value: `${fs}/9`,
        subtitle: quality.piotroski_grade,
        color: metricToneTextClass(tone),
        icon: "\u{1f4ca}",
        borderColor,
        metricKey: "piotroski_score",
      }
    })(),
    (() => {
      // Moat colouring follows the backend label mapping
      // (`_moat_label_from_score` in screener/moat_engine.py):
      //   Wide      → blue   (strong)
      //   Moderate  → green  (good; new band added 2026-04-23)
      //   Narrow    → amber  (acceptable)
      //   None / —  → red    (no durable advantage)
      const m = quality.moat
      const color =
        m === "Wide"     ? "text-tone-info-fg"
        : m === "Moderate" ? "text-green-700"
        : m === "Narrow"   ? "text-tone-warn-fg"
        :                    "text-tone-bad-fg"
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
      value: businessFlags.length === 0 ? "Clean ✓" : `${businessFlags.length} found`,
      subtitle: businessFlags.length > 0 ? businessFlags[0] : "No governance, accounting, or solvency concerns flagged",
      color: businessFlags.length === 0 ? "text-tone-info-fg" : "text-tone-bad-fg",
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
    // feat/earnings-calendar-unification:
    //   • If no date → return null and filter the card out below.
    //     The prior "Not scheduled" placeholder was misleading — it
    //     looked like an authoritative answer when in reality the
    //     NSE feed had simply blanked.
    //   • If days_until ≤ 7 → amber "Reports in Nd"
    //   • If days_until ≤ 14 → neutral "Reports next week"
    //   • confirmed=false → "Expected <date>" tentative
    (() => {
      const d = insights.earnings_date
      if (!d) return null
      const dt = new Date(d)
      const formatted = dt.toLocaleDateString("en-IN", {
        day: "numeric", month: "short", year: "numeric",
      })
      const du = insights.earnings_days_until
      const confirmed = insights.earnings_confirmed !== false  // legacy rows default true
      const fp = insights.earnings_fiscal_period
      let value = formatted
      let borderColor = "border-l-border"
      let color = "text-body"
      let subtitle: string
      if (!confirmed) {
        value = `Expected ${formatted}`
        subtitle = fp ? `Tentative · ${fp}` : "Tentative · not yet filed"
      } else if (du !== null && du !== undefined && du <= 7) {
        value = `Reports in ${du}d`
        color = "text-tone-warn-fg"
        borderColor = "border-l-amber-500"
        subtitle = `${formatted}${fp ? ` · ${fp}` : ""}`
      } else if (du !== null && du !== undefined && du <= 14) {
        value = "Reports next week"
        subtitle = `${formatted}${fp ? ` · ${fp}` : ""}`
      } else {
        const daysLabel = du !== null && du !== undefined ? ` (in ${du}d)` : ""
        subtitle = insights.earnings_est_eps !== null && insights.earnings_est_eps !== undefined
          ? `Est. EPS: ${insights.earnings_est_eps.toFixed(2)}${daysLabel}`
          : `Upcoming earnings${daysLabel}`
      }
      return {
        title: "Earnings",
        value,
        subtitle,
        color,
        icon: "\u{1f4c5}",
        borderColor,
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
          // Tickertape trick #4: color the yield value itself so the eye
          // catches "decent payer" vs "token yield" without reading the
          // sustainability tag below.
          color: metricToneTextClass(
            metricTone({ metric: "div_yield", value: yieldNum as number }),
          ),
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
    (() => {
      // Sprint A3 (2026-06-09, feat/sprint-a3-analyst-target-reframe):
      // Reframe the analyst card so it stops reading as a weakness when
      // no broker desk covers the name. Two states:
      //
      //   WITH-DATA  -> headline the YieldIQ FV (this product's number),
      //                 show the Street median right next to it, and let
      //                 the disagreement BE the insight via the
      //                 classifyAgreement helper (<5% / 5-15% / >15%).
      //   NO-DATA    -> keep the "Independent" framing but tighten the
      //                 copy so it reads confidently. Many of the best
      //                 opportunities sit outside the coverage universe.
      //
      // Both branches stay SEBI-clean: agreement copy routes through
      // classifyAgreement so vocabulary lives in one place. The richer
      // rating-distribution / price-target panel below
      // (AnalystConsensusPanel) still renders in the with-data case and
      // now carries the same agreement line for users who scroll past
      // the compact card.
      const ourFv =
        valuation && Number.isFinite(valuation.fair_value) ? valuation.fair_value : null
      const modelConf =
        valuation && Number.isFinite(valuation.model_confidence_score as number)
          ? (valuation.model_confidence_score as number)
          : null
      if (hasCoverage && analystConsensus) {
        const cnt = analystConsensus.coverage_count
        const street =
          analystConsensus.price_target?.median ?? analystConsensus.price_target?.mean ?? null
        const ourFmt = ourFv !== null && ourFv > 0 ? formatCurrency(ourFv, currency) : null
        const streetFmt = street !== null && street > 0 ? formatCurrency(street, currency) : null
        const agreement = classifyAgreement(ourFv, street)
        const subBits: string[] = []
        if (streetFmt) {
          subBits.push(`Street: ${streetFmt} (${cnt} analyst${cnt !== 1 ? "s" : ""})`)
        }
        if (agreement) subBits.push(agreement.short)
        const confidenceSuffix =
          modelConf !== null ? `, model confidence ${Math.round(modelConf)}%` : ""
        // Color + border come from the agreement band so the eye
        // catches "Street aligns with us" vs "we diverge from the
        // Street" without reading the subtitle.
        const borderClass =
          agreement?.band === "aligned" ? "border-l-blue-500"
          : agreement?.band === "moderate" ? "border-l-amber-500"
          : agreement?.band === "diverge" ? "border-l-red-500"
          : "border-l-border"
        const valueColor =
          agreement?.band === "aligned" ? "text-tone-info-fg"
          : agreement?.band === "moderate" ? "text-tone-warn-fg"
          : agreement?.band === "diverge" ? "text-tone-bad-fg"
          : "text-body"
        return {
          title: "Analyst Consensus (third-party)",
          // Value line = YieldIQ first (that is OUR number); Street
          // shows up in the subtitle alongside the agreement framing.
          value: ourFmt ? `YieldIQ: ${ourFmt}` : streetFmt ?? "\u2014",
          subtitle:
            subBits.length > 0 ? subBits.join(" \u00b7 ") : `DCF base case${confidenceSuffix}`,
          source: "Source: Finnhub \u2014 reference data only, not investment advice.",
          freshnessAt: analystConsensus.as_of ?? insights.analyst_target_as_of ?? null,
          freshnessPrefix: "As of",
          color: valueColor,
          icon: "\u{1f3af}",
          borderColor: borderClass,
        } as CardData
      }
      // Pre-feat/analyst legacy payload that DOES carry a Street number
      // on the flat insights object -- render the same YieldIQ vs Street
      // comparison off that field so older cached responses get the
      // reframe too.
      const legacyStreet = insights.wall_street_avg_target
      if (legacyStreet !== null && legacyStreet !== undefined && legacyStreet > 0) {
        const cnt = insights.wall_street_target_count
        const ourFmt = ourFv !== null && ourFv > 0 ? formatCurrency(ourFv, currency) : null
        const streetFmt = formatCurrency(legacyStreet, currency)
        const agreement = classifyAgreement(ourFv, legacyStreet)
        const analystCount =
          cnt !== null && cnt !== undefined && cnt > 0
            ? `${cnt} analyst${cnt !== 1 ? "s" : ""}`
            : "Analyst consensus"
        const subBits: string[] = [`Street: ${streetFmt} (${analystCount})`]
        if (agreement) subBits.push(agreement.short)
        const borderClass =
          agreement?.band === "aligned" ? "border-l-blue-500"
          : agreement?.band === "moderate" ? "border-l-amber-500"
          : agreement?.band === "diverge" ? "border-l-red-500"
          : "border-l-border"
        return {
          title: "Analyst Consensus (third-party)",
          value: ourFmt ? `YieldIQ: ${ourFmt}` : streetFmt,
          subtitle: subBits.join(" \u00b7 "),
          source: "Source: Finnhub \u2014 reference data only, not investment advice.",
          freshnessAt: insights.analyst_target_as_of ?? null,
          freshnessPrefix: "As of",
          color: "text-body",
          icon: "\u{1f3af}",
          borderColor: borderClass,
        } as CardData
      }
      // Truly no analyst coverage. Reframe as "Independent valuation":
      // many of the best opportunities sit outside the coverage universe
      // and broker coverage is not required for YieldIQ to estimate
      // intrinsic value from first-principles DCF.
      const ourFmt = ourFv !== null && ourFv > 0 ? formatCurrency(ourFv, currency) : null
      const confidenceSuffix =
        modelConf !== null ? `, model confidence ${Math.round(modelConf)}%` : ""
      const indepSubtitle = ourFmt
        ? `No third-party analyst coverage. YieldIQ values this name from first-principles DCF \u2014 many of the best opportunities sit outside the coverage universe. YieldIQ: ${ourFmt} (DCF base case${confidenceSuffix}).`
        : "No third-party analyst coverage. YieldIQ values this name from first-principles DCF \u2014 many of the best opportunities sit outside the coverage universe."
      return {
        title: "Analyst Coverage",
        value: "Independent",
        subtitle: indepSubtitle,
        source: "Source: Finnhub \u2014 reference data only, not investment advice.",
        color: "text-body",
        icon: "\u{1f3af}",
        borderColor: "border-l-border",
      } as CardData
    })(),
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
          subtitle: `${clientShort} ${qtyLabel} @ ${currencySymbol(currency, ticker)}${Math.round(latestDeal.price).toLocaleString(currencyLocale(currency, ticker))}`,
          color: latestDeal.deal_type === "BUY" ? "text-tone-info-fg" : "text-tone-bad-fg",
          icon: "\u{1f465}",
          borderColor: latestDeal.deal_type === "BUY" ? "border-l-blue-500" : "border-l-red-500",
        }
      }
      return {
        title: "Insider Activity",
        value: "Quiet ✓",
        subtitle: "No bulk or block deals filed in last 90 days",
        color: "text-tone-info-fg" as const,
        icon: "\u{1f465}",
        borderColor: "border-l-blue-500" as const,
      }
    })(),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ] as (CardData | null)[]).filter((c): c is CardData => c !== null), [quality, insights, valuation, currency, businessFlags.length, analystConsensus, hasCoverage])

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {cards.map((card) => (
          <div
            key={card.title}
            className={cn(
              "rounded-xl bg-surface border border-border border-l-[3px] p-4",
              "shadow-sm",
              // Premium Feel R1 — subtle hover lift on metric cards. 1.5%
              // scale + medium shadow reads as "interactive" without the
              // overstated 5% pop competitor sites use.
              "transition-transform duration-200 ease-out hover:scale-[1.015] hover:shadow-md",
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

      {/* Analyst Consensus panel (third-party, Finnhub).
          Rendered only when coverage_count > 0. The single card above
          carries the headline rating; this panel adds the rating
          distribution bar, price-target range, and EPS consensus.
          See backend/services/finnhub_analyst_service.py for the
          source data and TTL. SEBI compliance: every figure is
          sell-side analyst data, not a YieldIQ recommendation. */}
      {hasCoverage && analystConsensus ? (
        <AnalystConsensusPanel
          data={analystConsensus}
          currency={currency}
          ticker={ticker}
          valuation={valuation}
        />
      ) : null}

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
                // Premium Feel R1 — match the primary card grid hover lift.
                "transition-transform duration-200 ease-out hover:scale-[1.015] hover:shadow-md",
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
        <div className="rounded-xl bg-tone-warn-bg border border-amber-100 dark:bg-amber-950/30 dark:border-amber-900 p-4">
          <p className="text-xs font-semibold text-tone-warn-fg dark:text-amber-300 mb-2">Data Notes</p>
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


// ── Analyst Consensus panel (Finnhub) ──────────────────────────
// Renders rating distribution as a stacked horizontal bar, plus
// the price-target range (low / median / high) and EPS consensus
// for FY current + FY next. All values are third-party sell-side
// data sourced from Finnhub via the backend's
// finnhub_analyst_service. Reference data only — the disclaimer
// at the bottom is SEBI-compliance copy and must not be removed.

interface AnalystConsensusPanelProps {
  data: import("@/types/api").AnalystConsensus
  currency?: string | null
  ticker?: string
  /** Sprint A3: lets the panel render YieldIQ FV alongside the
   *  Street median + the "We agree within +/- X%" agreement line. */
  valuation?: ValuationOutput
}

function AnalystConsensusPanel({ data, currency, ticker: _ticker, valuation }: AnalystConsensusPanelProps) {
  const dist = data.rating_distribution
  const total = dist
    ? dist.strong_buy + dist.buy + dist.hold + dist.sell + dist.strong_sell
    : 0
  // Display labels are SEBI-compliant neutral terms. The underlying
  // ``dist`` keys (strong_buy / buy / hold / sell / strong_sell) are
  // wire-format object keys mirroring the Finnhub API and are exempted
  // by the SEBI lint's WIRE_FORMAT_LITERALS set — only the user-facing
  // ``label`` strings need sanitizing.
  const segs: { label: string; n: number; cls: string }[] = dist && total > 0
    ? [
        { label: "Highly Favorable", n: dist.strong_buy,  cls: "bg-blue-600" },
        { label: "Favorable",        n: dist.buy,         cls: "bg-blue-400" },
        { label: "Neutral",          n: dist.hold,        cls: "bg-amber-400" },
        { label: "Cautious",         n: dist.sell,        cls: "bg-red-400" },
        { label: "Highly Cautious",  n: dist.strong_sell, cls: "bg-red-600" },
      ]
    : []

  const pt = data.price_target
  const eps = data.eps_estimate
  const consensus = data.consensus_rating

  const consensusBadgeCls = (() => {
    const r = (consensus || "").toLowerCase()
    if (r.includes("highly favorable")) return "bg-blue-600 text-white"
    if (r.includes("favorable"))        return "bg-blue-100 text-blue-800 dark:bg-blue-950/40 dark:text-blue-200"
    if (r.includes("neutral"))          return "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
    if (r.includes("highly cautious"))  return "bg-red-600 text-white"
    if (r.includes("cautious"))         return "bg-red-100 text-red-800 dark:bg-red-950/40 dark:text-red-200"
    return "bg-muted text-body"
  })()

  return (
    <div className="rounded-xl bg-surface border border-border p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm">{"\u{1f3af}"}</span>
          <p className="text-xs font-semibold text-caption">
            Analyst Consensus (third-party)
          </p>
        </div>
        {consensus ? (
          <span className={cn(
            "text-xs font-semibold px-2 py-0.5 rounded-md uppercase tracking-wide",
            consensusBadgeCls,
          )}>
            {consensus}
          </span>
        ) : null}
      </div>

      <p className="text-xs text-caption mb-3">
        {data.coverage_count} analyst{data.coverage_count !== 1 ? "s" : ""} covering this stock
      </p>

      {/* Rating distribution bar */}
      {segs.length > 0 && total > 0 ? (
        <div className="mb-4">
          <div className="flex h-2 rounded-full overflow-hidden bg-muted/40">
            {segs.map((s) => s.n > 0 ? (
              <div
                key={s.label}
                className={cn("h-full", s.cls)}
                style={{ width: `${(s.n / total) * 100}%` }}
                title={`${s.label}: ${s.n}`}
              />
            ) : null)}
          </div>
          <div className="grid grid-cols-5 gap-1 mt-2 text-[11px] text-caption">
            {segs.map((s) => (
              <div key={s.label} className="flex flex-col items-center">
                <span className="font-semibold text-body">{s.n}</span>
                <span className="leading-tight text-center">{s.label}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* Sprint A3 (2026-06-09): YieldIQ vs Street headline pair +
          agreement classification + inline low/avg/high vertical bar
          with YieldIQ marker. Lifts the disagreement to the FIRST
          thing the user reads inside this panel so the comparison
          frame matches the compact card above. */}
      {pt && (pt.median || pt.mean) && valuation && Number.isFinite(valuation.fair_value) && valuation.fair_value > 0 ? (
        (() => {
          const street = pt.median ?? pt.mean ?? null
          const ourFv = valuation.fair_value
          const modelConf =
            Number.isFinite(valuation.model_confidence_score as number)
              ? (valuation.model_confidence_score as number)
              : null
          const agreement = classifyAgreement(ourFv, street)
          const ban = agreement?.band
          const txtCls =
            ban === "aligned" ? "text-tone-info-fg"
            : ban === "moderate" ? "text-tone-warn-fg"
            : ban === "diverge" ? "text-tone-bad-fg"
            : "text-body"
          return (
            <div className="mb-4">
              <div className="grid grid-cols-2 gap-3 mb-2">
                <div>
                  <p className="text-[11px] text-caption">Wall St avg target</p>
                  <p className="text-base font-semibold text-body">
                    {street ? formatCurrency(street, currency) : "—"}
                  </p>
                  <p className="text-[11px] text-caption">
                    {data.coverage_count} analyst{data.coverage_count !== 1 ? "s" : ""}
                  </p>
                </div>
                <div>
                  <p className="text-[11px] text-caption">YieldIQ fair value</p>
                  <p className="text-base font-semibold text-body">
                    {formatCurrency(ourFv, currency)}
                  </p>
                  <p className="text-[11px] text-caption">
                    DCF base case{modelConf !== null ? `, model confidence ${Math.round(modelConf)}%` : ""}
                  </p>
                </div>
              </div>
              {/* Inline low/avg/high horizontal bar with markers. The
                  filled span is the Street low->high range; a dot
                  marks the consensus mean/median; a vertical line
                  marks the YieldIQ FV. Skipped when low/high are
                  missing -- the agreement line below still renders. */}
              {pt.low && pt.high && pt.high > pt.low ? (
                (() => {
                  const lo = pt.low
                  const hi = pt.high
                  const mid = street ?? (lo + hi) / 2
                  const span = hi - lo
                  // Extend axis if YieldIQ falls outside the Street range
                  // so the marker is always visible inside the bar.
                  const axisLo = Math.min(lo, ourFv) - span * 0.05
                  const axisHi = Math.max(hi, ourFv) + span * 0.05
                  const axisSpan = axisHi - axisLo
                  const pct = (v: number) => `${((v - axisLo) / axisSpan) * 100}%`
                  return (
                    <div className="relative mt-1 mb-3 px-1" aria-label="Wall St target range with YieldIQ fair value marker">
                      <div className="relative h-2 rounded-full bg-muted/30">
                        {/* Street low->high band */}
                        <div
                          className="absolute h-2 rounded-full bg-blue-200 dark:bg-blue-900/50"
                          style={{ left: pct(lo), width: `calc(${pct(hi)} - ${pct(lo)})` }}
                        />
                        {/* Street median dot */}
                        <div
                          className="absolute -top-0.5 w-3 h-3 rounded-full bg-blue-500 border border-white dark:border-bg shadow-sm"
                          style={{ left: `calc(${pct(mid)} - 6px)` }}
                          title={`Street consensus: ${formatCurrency(mid, currency)}`}
                        />
                        {/* YieldIQ FV vertical tick */}
                        <div
                          className={cn(
                            "absolute -top-1 w-0.5 h-4",
                            ban === "aligned" ? "bg-tone-info-fg"
                            : ban === "moderate" ? "bg-tone-warn-fg"
                            : ban === "diverge" ? "bg-tone-bad-fg"
                            : "bg-body",
                          )}
                          style={{ left: pct(ourFv) }}
                          title={`YieldIQ fair value: ${formatCurrency(ourFv, currency)}`}
                        />
                      </div>
                      <div className="flex justify-between text-[10px] text-caption mt-1">
                        <span>{formatCurrency(lo, currency)}</span>
                        <span>{formatCurrency(hi, currency)}</span>
                      </div>
                    </div>
                  )
                })()
              ) : null}
              {agreement ? (
                <p className={cn("text-xs leading-snug", txtCls)}>{agreement.long}</p>
              ) : null}
            </div>
          )
        })()
      ) : null}

      {/* Price target range */}
      {pt && (pt.median || pt.mean || pt.high || pt.low) ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
          <div>
            <p className="text-[11px] text-caption">Median Target</p>
            <p className="text-sm font-semibold text-body">
              {pt.median ? formatCurrency(pt.median, currency) : "—"}
              {pt.vs_current_pct !== null && pt.vs_current_pct !== undefined ? (
                <span className={cn(
                  "ml-1 text-xs font-medium",
                  pt.vs_current_pct >= 0 ? "text-tone-info-fg" : "text-tone-bad-fg",
                )}>
                  ({pt.vs_current_pct >= 0 ? "+" : ""}{pt.vs_current_pct.toFixed(1)}%)
                </span>
              ) : null}
            </p>
          </div>
          <div>
            <p className="text-[11px] text-caption">Mean Target</p>
            <p className="text-sm font-semibold text-body">
              {pt.mean ? formatCurrency(pt.mean, currency) : "—"}
            </p>
          </div>
          <div>
            <p className="text-[11px] text-caption">Range Low</p>
            <p className="text-sm font-semibold text-body">
              {pt.low ? formatCurrency(pt.low, currency) : "—"}
            </p>
          </div>
          <div>
            <p className="text-[11px] text-caption">Range High</p>
            <p className="text-sm font-semibold text-body">
              {pt.high ? formatCurrency(pt.high, currency) : "—"}
            </p>
          </div>
        </div>
      ) : null}

      {/* EPS estimates */}
      {eps && (eps.fy_current !== null || eps.fy_next !== null) ? (
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <p className="text-[11px] text-caption">EPS — FY current</p>
            <p className="text-sm font-semibold text-body">
              {eps.fy_current !== null && eps.fy_current !== undefined
                ? eps.fy_current.toFixed(2)
                : "—"}
            </p>
          </div>
          <div>
            <p className="text-[11px] text-caption">EPS — FY next</p>
            <p className="text-sm font-semibold text-body">
              {eps.fy_next !== null && eps.fy_next !== undefined
                ? eps.fy_next.toFixed(2)
                : "—"}
            </p>
          </div>
        </div>
      ) : null}

      <p className="text-[11px] text-caption leading-snug border-t border-border pt-2">
        Source: {data.source || "Finnhub"} — reference data only, not investment advice.
        {data.as_of ? ` As of ${data.as_of}.` : ""}
      </p>
    </div>
  )
}
