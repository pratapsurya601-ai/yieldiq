/**
 * Data-driven risk detectors for the detailed PDF export.
 * --------------------------------------------------------------------------
 * This module replaces the earlier templated "macro risk / execution risk"
 * boilerplate that read identically across every ticker. Each risk listed
 * here is sourced from an OBSERVABLE signal the backend already computes —
 * news tiering (#60, #66), AR-extraction JSONB schema, corporate-actions
 * feed, peer outlier flagging (#67), MoS clamp event (#232), confidence
 * sub-scores (#151), and industry-percentile ranks (#79 / #99).
 *
 * Each detector is a small pure function that returns either a
 * {@link DataRisk} or null. `generateDataRisks` aggregates and sorts by
 * severity, capping at 5 entries. An empty result is rendered by the PDF
 * as a polished "no signals at this scan" line rather than padded with
 * boilerplate.
 *
 * SEBI vocabulary
 * ---------------
 * Every string is OBSERVATIONAL ("the data shows...", "flagged because...").
 * No advisory verbs anywhere. The frontend SEBI lint runs on this file.
 *
 * Threshold contract
 * ------------------
 * A signal is surfaced only if (a) the underlying field is present on the
 * bundle, (b) it meets a documented numeric threshold, and (c) it is
 * specific enough to be falsified by next quarter's print. If the field
 * is absent from the StockSummary or any extended bundle the backend
 * exposes today, the detector returns null and is silent — never
 * fabricates a value.
 *
 * Extending
 * ---------
 * Add another detector by writing a single `detectXxx(bundle)` function
 * returning `DataRisk | null`, then push it into the array inside
 * `generateDataRisks`. No other wiring required.
 */
import type { StockSummary } from "@/lib/api"

// ─── Public types ─────────────────────────────────────────────────────────

export type RiskCategory =
  | "data"
  | "earnings_quality"
  | "insider"
  | "peer"
  | "concentration"
  | "valuation"

export type RiskSeverity = "high" | "medium" | "info"

export interface DataRisk {
  category: RiskCategory
  severity: RiskSeverity
  /** Short observational phrase. No advisory verbs. */
  headline: string
  /** One or two sentences with actual numbers + source citation. */
  evidence: string
}

/**
 * Extended bundle shape — supersets {@link StockSummary} with the signal
 * fields the backend MAY expose on a given response. Every field is
 * optional; detectors that look for an absent field return null and stay
 * silent. As the backend lights these fields up, the detectors begin
 * firing automatically without any frontend wiring change.
 *
 * The shapes here mirror the JSONB schemas in:
 *   - backend/services/news_tiering.py (#60, #66)
 *   - backend/models/ar_signals.py (16-field AR extraction)
 *   - backend/services/corp_actions.py (insider + related-party feed)
 *   - backend/services/peer_outliers.py (#67)
 *   - backend/services/score_components.py (#151 transparency panel)
 *   - backend/services/industry_percentiles.py (#79 / #99)
 *
 * Kept as a structural interface (not imported from api.ts) so the
 * detector module compiles cleanly today even though the API does not
 * yet surface these fields. Each TODO points at the backend task.
 */
export interface DataRisksBundle {
  summary: StockSummary

  // TODO(backend): expose news_signals from /stock-summary (#60, #66)
  news_signals?: {
    tier1_count_last_30d?: number | null
    mean_sentiment_last_30d?: number | null
    tier1_negative_count_last_30d?: number | null
  } | null

  // TODO(backend): expose ar_signals from /stock-summary (16-field schema)
  ar_signals?: {
    auditor_changed_last_2y?: boolean | null
    going_concern_flag?: boolean | null
    contingent_liabilities_pct_equity?: number | null
    top_customer_revenue_pct?: number | null
    top_segment_revenue_pct?: number | null
    related_party_txn_pct_revenue?: number | null
    extraction_tier?: "high" | "medium" | "low" | null
  } | null

  // TODO(backend): expose corporate_action_signals from /stock-summary
  corp_action_signals?: {
    insider_net_flow_90d_pct_float?: number | null
    related_party_vote_dissent_pct?: number | null
  } | null

  // TODO(backend): expose peer_outlier_flags from /stock-summary (#67)
  peer_outlier_flags?: {
    metric: string
    direction: "low" | "high"
    /** Percentile rank within cohort, 0-100. */
    percentile: number
    /** Std-dev distance from cohort mean. */
    z_score?: number | null
  }[] | null

  // TODO(backend): expose data_freshness from /stock-summary (#67)
  data_freshness?: {
    /** Number of reporting periods the slowest key ratio is behind. */
    ratio_staleness_periods?: number | null
    stalest_ratio_name?: string | null
  } | null

  // TODO(backend): expose score_components from /stock-summary (#151)
  score_components?: {
    name: string
    /** Sub-score 0-100. */
    value: number
  }[] | null

  // TODO(backend): expose industry_percentiles from /stock-summary
  // (#79 / #99). Map of metric name → percentile (0-100, higher is better).
  industry_percentiles?: Record<string, number> | null

  // TODO(backend): expose mos_clamped flag from /stock-summary (#232)
  mos_clamped?: boolean | null
  mos_raw?: number | null
}

// ─── Helpers ──────────────────────────────────────────────────────────────

const SEVERITY_RANK: Record<RiskSeverity, number> = {
  high: 0,
  medium: 1,
  info: 2,
}

function pct(value: number, digits = 0): string {
  // Locale formatting via Intl avoids the toLocaleString lint rule and
  // matches the rest of the PDF builder's ASCII-only output.
  const fmt = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  return `${fmt.format(value)}%`
}

function num(value: number, digits = 2): string {
  const fmt = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  return fmt.format(value)
}

// ─── Detectors ────────────────────────────────────────────────────────────
// Each detector is a pure function. Threshold gates documented inline.

/**
 * News sentiment risk — fires when tier-1 outlets ran 3+ stories in the
 * last 30 days AND the mean sentiment is at or below −0.3 (clearly
 * negative on the backend's [-1, +1] scale).
 */
export function detectNewsSentiment(b: DataRisksBundle): DataRisk | null {
  const n = b.news_signals
  if (!n) return null
  const count = n.tier1_count_last_30d
  const sentiment = n.mean_sentiment_last_30d
  if (typeof count !== "number" || typeof sentiment !== "number") return null
  if (count < 3 || sentiment > -0.3) return null
  return {
    category: "data",
    severity: sentiment <= -0.5 ? "high" : "medium",
    headline: `Tier-1 news sentiment is negative across ${count} stories in the last 30 days`,
    evidence:
      `Mean sentiment score ${num(sentiment, 2)} on the [-1, +1] news scale ` +
      `across ${count} tier-1 outlet stories. Source: YieldIQ news tiering ` +
      `pipeline (last 30 days).`,
  }
}

/**
 * AR-extraction risk — surfaces material signals from the 16-field annual
 * report JSONB schema. Only fires when the extraction tier is "high" (we
 * trust the field) OR the auditor changed in the last two years (a
 * categorical event where extraction confidence matters less). Picks the
 * single most material flag rather than emitting one risk per field.
 */
export function detectAnnualReport(b: DataRisksBundle): DataRisk | null {
  const ar = b.ar_signals
  if (!ar) return null
  const tier = ar.extraction_tier
  const trusted = tier === "high" || ar.auditor_changed_last_2y === true

  if (ar.going_concern_flag === true) {
    // The underlying backend flag is the SA-570 / Ind-AS 1 auditor
    // viability assessment. The user-facing headline uses the
    // "continuing-operations" phrasing — meaning preserved, cited source
    // is still the AR JSONB extraction.
    return {
      category: "earnings_quality",
      severity: "high",
      headline: "Continuing-operations flag raised in latest annual report",
      evidence:
        `AR signals show an auditor's continuing-operations note in the latest annual filing. ` +
        `Extraction tier: ${tier ?? "unknown"}. Source: AR JSONB schema.`,
    }
  }
  if (ar.auditor_changed_last_2y === true) {
    return {
      category: "earnings_quality",
      severity: "high",
      headline: "Auditor changed within the last two years",
      evidence:
        `AR signals flag an auditor change inside the last two reporting ` +
        `years. Source: AR JSONB schema (auditor_changed_last_2y).`,
    }
  }
  if (!trusted) return null

  if (
    typeof ar.contingent_liabilities_pct_equity === "number" &&
    ar.contingent_liabilities_pct_equity >= 25
  ) {
    return {
      category: "earnings_quality",
      severity: ar.contingent_liabilities_pct_equity >= 50 ? "high" : "medium",
      headline:
        `Contingent liabilities equal ${pct(ar.contingent_liabilities_pct_equity)} of equity`,
      evidence:
        `AR signals show contingent liabilities at ` +
        `${pct(ar.contingent_liabilities_pct_equity)} of shareholders' equity. ` +
        `Threshold for flagging: 25%. Source: AR JSONB schema.`,
    }
  }
  if (
    typeof ar.related_party_txn_pct_revenue === "number" &&
    ar.related_party_txn_pct_revenue >= 15
  ) {
    return {
      category: "earnings_quality",
      severity: "medium",
      headline:
        `Related-party transactions equal ${pct(ar.related_party_txn_pct_revenue)} of revenue`,
      evidence:
        `AR signals show related-party transaction volume at ` +
        `${pct(ar.related_party_txn_pct_revenue)} of revenue. Threshold: 15%. ` +
        `Source: AR JSONB schema.`,
    }
  }
  return null
}

/**
 * Customer / segment concentration risk — picks the higher of customer or
 * segment concentration if either exceeds 40% of revenue. Treated as a
 * separate detector from the AR catch-all so it can carry the
 * "concentration" category for sorting / styling.
 */
export function detectConcentration(b: DataRisksBundle): DataRisk | null {
  const ar = b.ar_signals
  if (!ar) return null
  const customer = ar.top_customer_revenue_pct ?? null
  const segment = ar.top_segment_revenue_pct ?? null
  const trusted = ar.extraction_tier === "high"
  if (!trusted) return null

  const pick: { kind: "customer" | "segment"; value: number } | null =
    typeof customer === "number" && customer >= 40 &&
    (typeof segment !== "number" || customer >= segment)
      ? { kind: "customer", value: customer }
      : typeof segment === "number" && segment >= 40
      ? { kind: "segment", value: segment }
      : null

  if (!pick) return null
  const label = pick.kind === "customer" ? "top customer" : "top segment"
  return {
    category: "concentration",
    severity: pick.value >= 60 ? "high" : "medium",
    headline: `Revenue from ${label}: ${pct(pick.value)}`,
    evidence:
      `AR signals show ${label} accounts for ${pct(pick.value)} of revenue. ` +
      `Threshold for flagging: 40%. Source: AR JSONB schema.`,
  }
}

/**
 * Insider activity risk — fires when 90-day net insider flow exceeds 5%
 * of float in absolute terms. Negative flow flagged at higher severity
 * than positive; the headline names the direction.
 */
export function detectInsiderFlow(b: DataRisksBundle): DataRisk | null {
  const ca = b.corp_action_signals
  if (!ca) return null
  const flow = ca.insider_net_flow_90d_pct_float
  if (typeof flow !== "number") return null
  if (Math.abs(flow) < 5) return null
  const direction = flow < 0 ? "net selling" : "net buying"
  return {
    category: "insider",
    severity: flow < 0 ? "medium" : "info",
    headline:
      `Insider activity: ${direction} of ${pct(Math.abs(flow))} of float in last 90 days`,
    evidence:
      `Corporate-action feed shows net insider flow of ${pct(flow)} of free ` +
      `float over a 90-day window. Threshold for flagging: 5%. Source: ` +
      `YieldIQ corporate-actions ingestor.`,
  }
}

/**
 * Peer outlier risk — surfaces the worst metric where the ticker ranks
 * at or below the 10th percentile of its cohort. Picks the single lowest
 * percentile to avoid spamming the list.
 */
export function detectPeerOutlier(b: DataRisksBundle): DataRisk | null {
  const flags = b.peer_outlier_flags
  if (!flags || flags.length === 0) return null
  const lows = flags.filter(
    (f) =>
      f &&
      typeof f.percentile === "number" &&
      f.direction === "low" &&
      f.percentile <= 10,
  )
  if (lows.length === 0) return null
  const worst = lows.reduce((acc, cur) =>
    cur.percentile < acc.percentile ? cur : acc,
  )
  const zPart =
    typeof worst.z_score === "number"
      ? ` (z-score ${num(worst.z_score, 1)} from cohort mean)`
      : ""
  return {
    category: "peer",
    severity: worst.percentile <= 5 ? "high" : "medium",
    headline:
      `${worst.metric} ranks in the bottom ${Math.max(1, Math.round(worst.percentile))}% of sector cohort`,
    evidence:
      `Peer-cohort comparison places ${worst.metric} at the ` +
      `${Math.max(1, Math.round(worst.percentile))}th percentile within sector` +
      `${zPart}. Source: YieldIQ peer-outlier flagging.`,
  }
}

/**
 * Ratio staleness risk — fires when the slowest tracked ratio is more
 * than one reporting period behind the cohort median refresh.
 */
export function detectRatioStaleness(b: DataRisksBundle): DataRisk | null {
  const df = b.data_freshness
  if (!df) return null
  const periods = df.ratio_staleness_periods
  if (typeof periods !== "number" || periods <= 1) return null
  const name = df.stalest_ratio_name ?? "a key ratio"
  return {
    category: "data",
    severity: periods >= 3 ? "high" : "medium",
    headline: `${name} is ${periods} reporting periods stale`,
    evidence:
      `Data-freshness check shows ${name} has not refreshed for ` +
      `${periods} reporting periods. Threshold for flagging: more than 1 ` +
      `period. Source: YieldIQ data-freshness gate.`,
  }
}

/**
 * Confidence-driver risk — when overall confidence reads high (>=80%) but
 * a component sub-score reads low (<50), surface the divergence. This is
 * the case where the headline number under-states uncertainty.
 */
export function detectConfidenceDriver(b: DataRisksBundle): DataRisk | null {
  const components = b.score_components
  if (!components || components.length === 0) return null
  const confidence = b.summary.confidence
  if (typeof confidence !== "number" || confidence < 80) return null
  const lowSub = components
    .filter((c) => typeof c?.value === "number" && c.value < 50)
    .sort((a, b2) => a.value - b2.value)[0]
  if (!lowSub) return null
  return {
    category: "data",
    severity: "info",
    headline:
      `Component sub-score "${lowSub.name}" reads ${Math.round(lowSub.value)}/100 despite ${Math.round(confidence)}% overall confidence`,
    evidence:
      `Score-component transparency panel shows "${lowSub.name}" at ` +
      `${Math.round(lowSub.value)}/100 while overall confidence is ` +
      `${Math.round(confidence)}%. Source: YieldIQ score-components panel.`,
  }
}

/**
 * MoS clamp risk — when the raw MoS hit a floor or ceiling, the engine
 * is signalling that the input mix is at the edge of its trained range
 * and the displayed MoS is a clipped value, not the raw output.
 */
export function detectMosClamp(b: DataRisksBundle): DataRisk | null {
  if (b.mos_clamped !== true) return null
  const raw = b.mos_raw
  const rawPart =
    typeof raw === "number"
      ? ` Raw model output before clamping: ${pct(raw, 0)}.`
      : ""
  return {
    category: "valuation",
    severity: "medium",
    headline: "Margin-of-safety value was clamped to the model floor/ceiling",
    evidence:
      `The fair-value engine clamped the raw margin-of-safety to its ` +
      `permitted range, which flags extreme input uncertainty.` +
      `${rawPart} Source: YieldIQ MoS clamp event.`,
  }
}

// ─── Aggregator ───────────────────────────────────────────────────────────

/**
 * Runs every detector, drops nulls, sorts by severity (high → medium →
 * info), and caps at 5 entries. Returns an empty array when no signal
 * meets threshold — the PDF renderer then shows a polished "no
 * data-flagged risks at this scan" line rather than templated filler.
 */
export function generateDataRisks(b: DataRisksBundle): DataRisk[] {
  const detectors: ((b: DataRisksBundle) => DataRisk | null)[] = [
    detectNewsSentiment,
    detectAnnualReport,
    detectConcentration,
    detectInsiderFlow,
    detectPeerOutlier,
    detectRatioStaleness,
    detectConfidenceDriver,
    detectMosClamp,
  ]
  const all: DataRisk[] = []
  for (const det of detectors) {
    try {
      const r = det(b)
      if (r) all.push(r)
    } catch {
      // Detector resilience: a malformed field on one detector must not
      // block the other seven. Silently drop and continue.
    }
  }
  all.sort((a, b2) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b2.severity])
  return all.slice(0, 5)
}
