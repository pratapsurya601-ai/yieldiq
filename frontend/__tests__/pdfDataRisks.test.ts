/**
 * Detector-by-detector tests for the data-driven PDF risks panel.
 *
 * The harness is intentionally hand-rolled — no fancy fixtures — so a
 * reviewer can read each case and verify the threshold logic by eye.
 * Three cases the brief asked for: no-signal, all-signals, and
 * resilience against null-valued signal fields.
 */
import { describe, it, expect } from "vitest"
import {
  generateDataRisks,
  detectNewsSentiment,
  detectAnnualReport,
  detectConcentration,
  detectInsiderFlow,
  detectPeerOutlier,
  detectRatioStaleness,
  detectConfidenceDriver,
  detectMosClamp,
  type DataRisksBundle,
} from "@/lib/pdf-data-risks"
import type { StockSummary } from "@/lib/api"

function summary(overrides: Partial<StockSummary> = {}): StockSummary {
  return {
    ticker: "ACME",
    company_name: "Acme Industries",
    sector: "Industrials",
    industry: "Capital goods",
    exchange: "NSE",
    currency: "INR",
    fair_value: 1000,
    current_price: 800,
    mos: 20,
    verdict: "below_fair_value",
    score: 70,
    grade: "B+",
    moat: "narrow",
    piotroski: 6,
    bear_case: 700,
    base_case: 1000,
    bull_case: 1300,
    wacc: 0.11,
    confidence: 75,
    roe: 12,
    de_ratio: 0.6,
    roce: 14,
    debt_ebitda: 1.8,
    interest_coverage: 5,
    current_ratio: 1.3,
    asset_turnover: 0.9,
    revenue_cagr_3y: 0.1,
    revenue_cagr_5y: 0.09,
    ev_ebitda: 13,
    market_cap: 50000,
    ai_summary_snippet: null,
    compounded_growth: null,
    last_updated: "2026-06-01",
    ...overrides,
  }
}

describe("generateDataRisks — empty bundle", () => {
  it("returns no risks when no signal fields are present", () => {
    const result = generateDataRisks({ summary: summary() })
    expect(result).toEqual([])
  })

  it("returns no risks when signal fields are present but below threshold", () => {
    const result = generateDataRisks({
      summary: summary(),
      news_signals: { tier1_count_last_30d: 1, mean_sentiment_last_30d: -0.1 },
      corp_action_signals: { insider_net_flow_90d_pct_float: 1 },
      peer_outlier_flags: [
        { metric: "ROCE", direction: "low", percentile: 50 },
      ],
      data_freshness: { ratio_staleness_periods: 1 },
      mos_clamped: false,
    })
    expect(result).toEqual([])
  })
})

describe("generateDataRisks — all signals firing", () => {
  it("returns risks sorted by severity and capped at 5", () => {
    const bundle: DataRisksBundle = {
      summary: summary({ confidence: 92 }),
      news_signals: {
        tier1_count_last_30d: 8,
        mean_sentiment_last_30d: -0.6,
      },
      ar_signals: {
        extraction_tier: "high",
        going_concern_flag: true,
        auditor_changed_last_2y: true,
        contingent_liabilities_pct_equity: 80,
        top_customer_revenue_pct: 65,
        top_segment_revenue_pct: 70,
        related_party_txn_pct_revenue: 25,
      },
      corp_action_signals: {
        insider_net_flow_90d_pct_float: -12,
      },
      peer_outlier_flags: [
        { metric: "Asset turnover", direction: "low", percentile: 3, z_score: -2.4 },
        { metric: "ROCE", direction: "low", percentile: 8 },
      ],
      data_freshness: {
        ratio_staleness_periods: 4,
        stalest_ratio_name: "Net interest margin",
      },
      score_components: [
        { name: "Earnings quality", value: 35 },
        { name: "Balance sheet", value: 75 },
      ],
      mos_clamped: true,
      mos_raw: 92,
    }

    const result = generateDataRisks(bundle)
    expect(result.length).toBeLessThanOrEqual(5)
    expect(result.length).toBeGreaterThan(0)
    // Severity must be monotonically non-decreasing (high → medium → info).
    const rank = { high: 0, medium: 1, info: 2 } as const
    for (let i = 1; i < result.length; i++) {
      const prev = result[i - 1]
      const cur = result[i]
      if (prev && cur) {
        expect(rank[prev.severity]).toBeLessThanOrEqual(rank[cur.severity])
      }
    }
    // At least one high-severity risk is present (going-concern fires high).
    expect(result.some((r) => r.severity === "high")).toBe(true)
  })

  it("contains no banned advisory verbs in headlines or evidence", () => {
    const bundle: DataRisksBundle = {
      summary: summary(),
      news_signals: { tier1_count_last_30d: 5, mean_sentiment_last_30d: -0.4 },
      ar_signals: {
        extraction_tier: "high",
        contingent_liabilities_pct_equity: 60,
      },
      corp_action_signals: { insider_net_flow_90d_pct_float: -8 },
      peer_outlier_flags: [
        { metric: "ROCE", direction: "low", percentile: 4 },
      ],
      data_freshness: {
        ratio_staleness_periods: 2,
        stalest_ratio_name: "Operating margin",
      },
      mos_clamped: true,
    }
    const result = generateDataRisks(bundle)
    // Mirrors backend SEBI_filter banned vocabulary (advisory verbs only).
    const banned = /\b(buy|sell|hold|recommend|should|appears|outperform|underperform|accumulate|cheap|expensive|attractive)\b/i
    for (const r of result) {
      expect(r.headline).not.toMatch(banned)
      expect(r.evidence).not.toMatch(banned)
    }
  })
})

describe("generateDataRisks — null-field resilience", () => {
  it("does not throw and returns empty when signal blocks are present but every inner field is null", () => {
    const bundle: DataRisksBundle = {
      summary: summary(),
      news_signals: {
        tier1_count_last_30d: null,
        mean_sentiment_last_30d: null,
      },
      ar_signals: {
        extraction_tier: null,
        going_concern_flag: null,
        auditor_changed_last_2y: null,
        contingent_liabilities_pct_equity: null,
        top_customer_revenue_pct: null,
        top_segment_revenue_pct: null,
        related_party_txn_pct_revenue: null,
      },
      corp_action_signals: { insider_net_flow_90d_pct_float: null },
      peer_outlier_flags: [],
      data_freshness: { ratio_staleness_periods: null },
      score_components: [],
      mos_clamped: null,
    }
    expect(() => generateDataRisks(bundle)).not.toThrow()
    expect(generateDataRisks(bundle)).toEqual([])
  })

  it("skips a single faulty detector without blocking the others", () => {
    // peer_outlier_flags contains a malformed entry (percentile is a
    // string) — the catch wrapper inside generateDataRisks must keep
    // the rest of the detectors flowing.
    const bundle = {
      summary: summary(),
      peer_outlier_flags: [{ metric: "X", direction: "low", percentile: "broken" }],
      mos_clamped: true,
    } as unknown as DataRisksBundle
    const result = generateDataRisks(bundle)
    expect(result.some((r) => r.category === "valuation")).toBe(true)
  })
})

describe("individual detectors — threshold gates", () => {
  it("detectNewsSentiment is null below the 3-story floor", () => {
    expect(
      detectNewsSentiment({
        summary: summary(),
        news_signals: {
          tier1_count_last_30d: 2,
          mean_sentiment_last_30d: -0.9,
        },
      }),
    ).toBeNull()
  })

  it("detectAnnualReport returns null when extraction tier is low and event is not categorical", () => {
    expect(
      detectAnnualReport({
        summary: summary(),
        ar_signals: {
          extraction_tier: "low",
          contingent_liabilities_pct_equity: 80,
        },
      }),
    ).toBeNull()
  })

  it("detectConcentration requires high extraction tier", () => {
    expect(
      detectConcentration({
        summary: summary(),
        ar_signals: {
          extraction_tier: "medium",
          top_customer_revenue_pct: 70,
        },
      }),
    ).toBeNull()
  })

  it("detectInsiderFlow ignores flows under 5% of float", () => {
    expect(
      detectInsiderFlow({
        summary: summary(),
        corp_action_signals: { insider_net_flow_90d_pct_float: 3 },
      }),
    ).toBeNull()
  })

  it("detectPeerOutlier ignores rankings above the 10th percentile", () => {
    expect(
      detectPeerOutlier({
        summary: summary(),
        peer_outlier_flags: [
          { metric: "ROCE", direction: "low", percentile: 25 },
        ],
      }),
    ).toBeNull()
  })

  it("detectRatioStaleness ignores 1-period drift", () => {
    expect(
      detectRatioStaleness({
        summary: summary(),
        data_freshness: { ratio_staleness_periods: 1 },
      }),
    ).toBeNull()
  })

  it("detectConfidenceDriver requires overall confidence at or above 80", () => {
    expect(
      detectConfidenceDriver({
        summary: summary({ confidence: 70 }),
        score_components: [{ name: "Earnings quality", value: 30 }],
      }),
    ).toBeNull()
  })

  it("detectMosClamp is silent when clamp flag is false", () => {
    expect(detectMosClamp({ summary: summary(), mos_clamped: false })).toBeNull()
  })
})
