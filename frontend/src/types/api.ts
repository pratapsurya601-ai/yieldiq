// types/api.ts — mirrors backend/models/responses.py exactly

// Day-61 (2026-05-21): "low_confidence" added as a first-class verdict.
// The hero renders it instead of confident undervalued/overvalued when
// the model's own confidence drops below 50% --- a sub-50% confidence
// number on a confidently-coloured pill was the audit's #2 trust hit.
export type Verdict = "undervalued" | "fairly_valued" | "overvalued" | "avoid" | "data_limited" | "unavailable" | "low_confidence"
export type Grade = "A" | "B" | "C" | "D" | "F"
export type Tier = "free" | "starter" | "pro" | "analyst"
export type Confidence = "high" | "medium" | "low" | "unusable"
// Mirrors backend QualityOutput.moat Literal at backend/models/responses.py:67.
// "Moderate" is emitted for allowlisted bellwethers floored by PR #36 / PR #41
// (score >=60). "N/A (Financial)" is emitted for banks/NBFCs where the moat
// engine returns a sector-specific sentinel. Drift between this union and the
// backend Literal silently breaks the Vercel build via InsightCards.tsx moat
// card comparisons — keep them synchronized.
export type MoatGrade = "Wide" | "Moderate" | "Narrow" | "None" | "N/A (Financial)"

export interface CompanyInfo {
  ticker: string
  company_name: string
  exchange: string
  sector: string
  industry: string
  country: string
  currency: string
  logo_url: string | null
  description: string | null
  market_cap: number
  employees: number | null
  // feat/transparency (2026-05-02) — provenance for the market-cap
  // hero number / freshness widget. Optional for back-compat.
  market_cap_as_of?: string | null
  market_cap_source?: string | null
  shares_outstanding_source?: string | null
}

export interface ValuationOutput {
  fair_value: number
  current_price: number
  margin_of_safety: number
  // Step B (2026-05-17): true Buffett margin of safety = (FV-CP)/FV*100.
  // Distinct from `margin_of_safety` above which is upside % (denominator
  // is current price). Optional + nullable for back-compat with cached
  // payloads that pre-date the field.
  buffett_mos_pct?: number | null
  verdict: Verdict
  bear_case: number
  base_case: number
  bull_case: number
  wacc: number
  terminal_growth: number
  fcf_growth_rate: number
  confidence_score: number
  wacc_industry_min: number
  wacc_industry_max: number
  fcf_growth_historical_avg: number
  tv_pct_of_ev: number
  dcf_reliable: boolean
  reliability_score: number
  pv_fcfs: number
  pv_terminal: number
  enterprise_value: number
  equity_value: number
  margin_of_safety_display: number
  mos_is_extreme: boolean
  mos_extreme_note: string | null
  fcf_data_source: string  // "ttm", "annual", or "yfinance"
  // feat/freshness-stamps — ISO timestamp of last price pull. Null on
  // legacy/degraded payloads. Render via <FreshnessStamp prefix="Delayed" />;
  // never "Live" (SEBI discipline, prices are always delayed).
  current_price_as_of?: string | null
  // Task #197 (feat/as-of-plumbing, 2026-05-24) — actual live_quotes.as_of
  // timestamp (refreshed ~5m). Lets the FreshnessStamp pick the right tier:
  // <30m green "Live", 30m-4h yellow "Delayed", >4h red "Stale". Null when
  // the canonical cascade fell through to daily_prices / yfinance (frontend
  // falls back to current_price_as_of, then to "Updated recently").
  as_of?: string | null
  // feat/transparency (2026-05-02) — per-number provenance surfaced
  // in hero tooltips + freshness widget. Optional for back-compat with
  // pre-PR cached payloads.
  current_price_source?: string | null
  fair_value_computed_at?: string | null
  valuation_engine_used?: string | null

  // Defense-PSU NO-FIX flag (PR #333, 2026-05-18 — see
  // docs/design/defense-psu-dcf-fix.md, Approach D). True when the
  // trailing-financials DCF systematically understates forward
  // earning power (Make-in-India order-book regime change). Frontend
  // renders an "Analyst Opinion Required" banner above the FV.
  analyst_opinion_required?: boolean | null

  // Layer C — Confidence Framework scores (PRs #340 + #342,
  // 2026-05-18). Three 0-100 ints produced by
  // backend.services.confidence_service. Optional so legacy cached
  // payloads remain valid. Frontend renders chips via
  // <ConfidenceIndicators />; if all three are null/undefined the
  // band is hidden entirely.
  //   data_quality_score        — completeness/freshness of inputs
  //   model_confidence_score    — engine fit for this business
  //   valuation_stability_score — variance of FV over recent weeks
  data_quality_score?: number | null
  model_confidence_score?: number | null
  valuation_stability_score?: number | null

  // T2.7 (2026-06-09) — 4th confidence pillar. Monte Carlo
  // sensitivity: fraction of 200 perturbed runs that preserve the
  // base verdict. Optional — null for holdcos (SOTP-shaped) and
  // banks (residual-income-shaped). Surfaced by <ConfidenceRadar>.
  confidence_sensitivity?: number | null

  // T1.6 (2026-06-10) — 5th confidence pillar. Composite-agreement
  // score: how tightly the composite-IV constituent estimators
  // cluster (high = agree, low = wide spread). Optional — null
  // when the composite path runs a single estimator. Surfaced by
  // <ConfidenceRadar>.
  confidence_composite_agreement?: number | null
}

// Phase C.3 (2026-05-25) — score breakdown for the "Why this score?"
// panel. Mirrors backend/models/responses.py::ScoreBreakdown.
// Field-additive: legacy cached payloads return null/undefined.
export interface ScoreComponent {
  name: string
  weight_max: number
  points: number
  source: string
}
export interface ScoreModifier {
  name: string
  delta: number
  reason: string
}
export interface ScoreBreakdown {
  components: ScoreComponent[]
  modifiers: ScoreModifier[]
  base_score: number
  final_score: number
  note?: string | null
}

export interface QualityOutput {
  yieldiq_score: number
  grade: string
  score_breakdown?: ScoreBreakdown | null
  piotroski_score: number
  piotroski_grade: string
  earnings_quality_grade: string
  earnings_quality_score: number
  moat: MoatGrade
  moat_score: number
  momentum_score: number
  momentum_grade: string
  fundamental_score: number
  fundamental_grade: string
  roe: number | null
  de_ratio: number | null
  roce?: number | null
  debt_ebitda?: number | null
  debt_ebitda_label?: string | null
  interest_coverage?: number | null
  enterprise_value?: number | null
  // Phase 2.1 additions — backfilled by backend (see backend/models/responses.py
  // QualityOutput). Added to the frontend type on 2026-04-22 to wire up the
  // three ratio cards that were already coming down the wire but silently
  // dropped by the render list.
  current_ratio?: number | null     // ratio, current_assets / current_liabilities
  asset_turnover?: number | null    // ratio, revenue / total_assets
  revenue_cagr_3y?: number | null   // DECIMAL (0.124 = 12.4%) — multiply by 100 to display
  revenue_cagr_5y?: number | null   // DECIMAL
  promoter_pct?: number | null
  promoter_pledge_pct?: number | null
  // Override metadata from data_pipeline/data/promoter_overrides.json.
  // type: "foreign_promoter" | "no_promoter_bank" | "govt_promoter" | "domestic_promoter"
  promoter_holding_type?: string | null
  promoter_entity?: string | null
  fii_pct?: number | null
  dii_pct?: number | null
  public_pct?: number | null
  // Bank-native metrics — present for banks/NBFCs, null elsewhere.
  // See docs/bank_data_availability.md for the coverage matrix.
  is_bank?: boolean
  roa?: number | null              // percent
  cost_to_income?: number | null   // percent
  advances_yoy?: number | null     // percent, proxied via total_assets YoY
  deposits_yoy?: number | null     // percent, proxied via total_liab YoY
  revenue_yoy_bank?: number | null // percent
  pat_yoy_bank?: number | null     // percent
  nim?: number | null              // percent — null until NSE XBRL Sch A/B lands
  car?: number | null              // percent — null until NSE XBRL Sch XI lands
  nnpa?: number | null             // percent — null until NSE XBRL Sch XVIII lands
  casa?: number | null             // percent — null until NSE XBRL Sch V lands
  // feat/freshness-stamps — period_end (YYYY-MM-DD) of the latest
  // filing feeding these ratios. Null on yfinance-only paths.
  latest_filing_period_end?: string | null
  // feat/transparency (2026-05-02) — provenance for the revenue-CAGR
  // metric. Window is "3y" / "5y"; source is the data path used.
  revenue_cagr_window?: string | null
  revenue_source?: string | null
}

export interface BulkDealItem {
  date: string
  client: string
  deal_type: string
  qty_lakh: number
  price: number
  category: string
}

export interface RedFlag {
  flag: string
  severity: "critical" | "warning" | "info"
  title: string
  explanation: string
  data_point: string
  why_it_matters: string
}

export interface DividendFYItem {
  fy: string
  total_per_share: number
  payment_count: number
}

export interface DividendData {
  has_dividends: boolean
  ticker: string
  message: string
  current_yield_pct: number | null
  payout_ratio_pct: number | null
  five_yr_avg_yield: number | null
  dividend_rate_per_share: number | null
  last_dividend_value: number | null
  next_ex_date: string | null
  next_ex_days: number | null
  consecutive_years: number
  fy_history: DividendFYItem[]
  coverage_ratio: number | null
  sustainability: "strong" | "moderate" | "at_risk"
  sustainability_reason: string
  // feat/freshness-stamps — ISO date (YYYY-MM-DD) of the last ex-dividend event.
  last_ex_date?: string | null
}

export interface InsightCards {
  patience_months: number | null
  red_flag_count: number
  red_flags: string[]
  red_flags_structured: RedFlag[]
  dividend?: DividendData | null
  earnings_date: string | null
  earnings_est_eps: number | null
  earnings_days_until: number | null
  // feat/earnings-calendar-unification — provenance + confidence
  earnings_confirmed?: boolean | null
  earnings_source?: string | null
  earnings_fiscal_period?: string | null
  wall_street_avg_target: number | null
  wall_street_target_count: number | null
  insider_net_sentiment: string | null
  market_expectations_growth: number | null
  fcf_yield: number | null
  ev_ebitda: number | null
  reverse_dcf_implied_growth: number | null
  bulk_deals: BulkDealItem[]
  // feat/freshness-stamps — ISO timestamp of the analyst consensus refresh.
  // Null when unavailable; backend falls back to compute time when any
  // target data is present.
  analyst_target_as_of?: string | null
}

export interface ScenarioCase {
  iv: number
  mos_pct: number
  growth: number
  wacc: number
  term_g: number
}

export interface ScenariosOutput {
  bear: ScenarioCase
  base: ScenarioCase
  bull: ScenarioCase
}

export interface PriceLevels {
  entry_signal: string
  discount_zone: number | null
  model_estimate: number | null
  downside_range: number | null
  risk_reward_ratio: number | null
  holding_period: string | null
}

// Mirrors backend AnalyticalNoteOutput at backend/models/responses.py
// (PR #69). Backend emits 0-5 contextual disclaimers per analysis flagging
// structural DCF limitations for specific stock archetypes (premium brand,
// conglomerate, regulated utility, cyclical trough, post-merger, high-P/E
// growth, ADR / USD reporting).
export type AnalyticalNoteKind =
  | "data_quality"
  | "premium_brand"
  | "conglomerate"
  | "regulated_utility"
  | "cyclical_trough"
  | "post_merger"
  | "high_pe_growth"
  | "adr_usd_reporting"
export type AnalyticalNoteSeverity = "info" | "caution"
export interface AnalyticalNoteOutput {
  kind: AnalyticalNoteKind
  severity: AnalyticalNoteSeverity
  title: string
  body: string
}

// ── Finnhub analyst consensus ───────────────────────────────
// Third-party reference data, rendered alongside the existing
// "Analyst Consensus (third-party)" card. Backend lives at
// backend/services/finnhub_analyst_service.py — purely additive,
// gracefully degrades to `coverage_count: 0` when Finnhub returns
// no coverage for the ticker (typical for small-cap Indian listings).

export interface AnalystRatingDistribution {
  strong_buy: number
  buy: number
  hold: number
  sell: number
  strong_sell: number
}

export interface AnalystPriceTarget {
  median: number | null
  mean: number | null
  high: number | null
  low: number | null
  vs_current_pct: number | null
}

export interface AnalystEpsEstimate {
  fy_current: number | null
  fy_next: number | null
}

export interface AnalystConsensus {
  coverage_count: number
  rating_distribution: AnalystRatingDistribution | null
  consensus_rating: string | null
  price_target: AnalystPriceTarget | null
  eps_estimate: AnalystEpsEstimate | null
  as_of: string | null
  source: string
}

/**
 * The Honest Card payload — see backend/services/analysis/
 * honest_card_generator.py for rule logic.
 */
export interface HonestCardOutput {
  confident_facts: string[]
  best_estimate: string
  uncertainty_factors: string[]
  invalidating_conditions: string[]
}

export interface AnalysisResponse {
  ticker: string
  company: CompanyInfo
  valuation: ValuationOutput
  quality: QualityOutput
  insights: InsightCards
  scenarios: ScenariosOutput
  price_levels: PriceLevels
  ai_summary: string | null
  /**
   * Multilingual AI summary translations (Phase 0 — review-gated,
   * dark-launched). Mirrors the backend's
   * `AnalysisResponse.ai_summary_translations`. Keyed by ISO 639-1
   * code: "hi" (Hindi), "ta" (Tamil), "mr" (Marathi). The English
   * summary in `ai_summary` is the authoritative source; translations
   * carry an in-string disclaimer noting this. Stays `null` until
   * the `MULTILINGUAL_SUMMARIES_ENABLED` backend flag is flipped
   * (post native-speaker review). UI toggle ships in a later PR.
   */
  ai_summary_translations?: Record<string, string> | null
  data_confidence: Confidence
  data_issues: string[]
  analytical_notes?: AnalyticalNoteOutput[]
  /**
   * Third-party analyst data sourced from Finnhub (rating distribution,
   * price targets, EPS consensus). Optional for backwards compatibility:
   * existing cached payloads will lack this field, in which case the
   * frontend falls back to the legacy "No coverage" rendering driven by
   * `insights.wall_street_avg_target`.
   */
  analyst_consensus?: AnalystConsensus | null
  cached: boolean
  timestamp: string
  /**
   * Task #197 (feat/as-of-plumbing) — top-level mirror of
   * `valuation.as_of` (the live_quotes.as_of for the row that produced
   * `valuation.current_price`). Lets the AnalysisHero render the
   * FreshnessStamp without unwrapping `valuation`. Null when the
   * canonical cascade fell through to daily_prices / yfinance.
   */
  as_of?: string | null
  /**
   * Bulls Say / Bears Say structured narratives (P0 #4, 2026-05-25).
   * Up to 3 short factual bullets each, generated by
   * backend/services/analysis/bulls_bears_generator.py. Pure
   * rule + template output, SEBI-safe by construction. Optional —
   * legacy cached payloads predate the field, in which case the
   * <BullsBearsPanel /> renders the "Insufficient data" empty state.
   */
  bulls_say?: string[] | null
  bears_say?: string[] | null
  /**
   * v_238 (2026-05-26) — paragraph upgrade. Composed bull / bear
   * narratives: the top-3 bullets joined into a single block of prose.
   * Useful for surfaces (PDF export, OG card) that prefer one
   * paragraph over an array of bullets. Optional — None on legacy
   * cached payloads.
   */
  bull_case_narrative?: string | null
  bear_case_narrative?: string | null
  /**
   * "Month YYYY" stamp for the thesis panel (e.g. "April 2026"),
   * derived from valuation.fair_value_computed_at. Lets the panel
   * render a dated header (matching the convention competitor
   * research notes use) instead of evergreen copy. Optional.
   */
  thesis_updated?: string | null
  /**
   * The Honest Card (Phase 3 manifesto, 2026-05-25). Radical-
   * transparency panel — confident facts, best-estimate sentence,
   * uncertainty factors, and exactly 3 invalidating conditions.
   * Generated server-side by backend/services/analysis/
   * honest_card_generator.py (no LLM, SEBI-safe). Optional — legacy
   * cached payloads predate the field; the <HonestCard /> component
   * self-hides when absent.
   */
  honest_card?: HonestCardOutput | null
  /**
   * The Worry Index (Phase-3, 2026-05-25) — 0-100 emotional risk
   * composite plus tier copy. See backend/services/analysis/worry_index.py.
   * Renders via <WorryIndex /> on the Summary tab between the hero and
   * "1. VALUATION SCENARIOS". Optional — pre-PR cached payloads omit it.
   */
  worry_index?: {
    score: number
    tier:
      | "sleep_well"
      | "normal"
      | "watch_closely"
      | "read_bears"
      | "significant_concerns"
    headline: string
    contributors: Array<{
      component: string
      label: string
      weight: number
      score: number
      detail?: string
    }>
  } | null
  /**
   * Per-metric peer percentile context for inline comparison sliders.
   * See backend/services/analysis/peer_context.py. Keyed by metric id
   * (e.g. "roe_pct", "pe_ratio"). Each block carries {value, median,
   * p5, p95, n}. Read by <MetricWithContext /> on the Quality tab.
   */
  peer_context?: Record<string, {
    value: number | null
    median: number
    p5: number
    p95: number
    n: number
  }> | null
  /**
   * Inline sector-median chips (2026-05-27, Tickertape density trick
   * #2). Five reference medians for the ticker's Day-108c cohort —
   * read by <MetricVsSectorChip /> on the analysis page to render
   * "Sector X" context beside every primary ratio. Each value is null
   * when the ticker sits outside a curated cohort, when the cohort
   * has no cached members, or when the underlying metric is missing
   * on every cohort row. The chip self-hides per metric in that case.
   * Backend: backend/services/sector_medians_for_ticker.py.
   */
  sector_medians?: {
    pe: number | null
    pb: number | null
    roe: number | null
    div_yield: number | null
    op_margin: number | null
  } | null
  /**
   * DCF + Multiples cross-confirmation (Sprint A2, 2026-06-09).
   * `multiples_based_fv` is a peer-relative re-pricing of the current
   * quote — "what would this stock be worth if it traded at the
   * sector-median multiple?" — NOT a separate valuation model.
   * Computed from the response's own PE / PB and the sector_medians
   * cohort medians (backend/services/multiples_fv.py).
   *
   * Both fields are null when no peer cohort, when the ticker's own
   * multiple is missing / non-positive, or when the cohort median
   * is missing (banks special case, fresh listings). The
   * <DcfMultiplesChip /> pill row self-hides in that case.
   *
   * `multiples_method` documents which multiple drove the path:
   * "pe" by default, "pb" as fallback (banks / financial services),
   * "ev_ebitda" reserved for a future path.
   */
  multiples_based_fv?: number | null
  multiples_method?: "pe" | "pb" | "ev_ebitda" | null
  /**
   * T5.10 — per-engine valuation methods panel (engine-refinement
   * transparency surface). All fields are OPTIONAL and gracefully
   * absent on legacy / pre-T1.1 / pre-PR-#803 cached payloads. The
   * <ValuationMethodsPanel /> renders only the methods whose value is
   * non-null; everything else collapses into the "not applicable for
   * this ticker" footnote.
   *
   * `composite_intrinsic_value` — T1.1 weighted-average of DCF +
   *   Peer Multiples + Wall Street consensus. `composite_components`
   *   carries the per-input contribution + the method tag used.
   *
   * `three_stage_fv` / `ddm_fv` / `epv_per_share` /
   * `liquidation_per_share` / `probability_weighted_fv` — Phase B
   *   (#803) standalone-service outputs. Null when the ticker does
   *   not meet the service's applicability gate (e.g. DDM requires
   *   payout >= 30% and a 5y dividend streak; Liquidation excludes
   *   asset-light / financial businesses).
   *
   * The companion `*_method` strings document which sub-flavour of
   * each model produced the figure (e.g. "two_stage", "h_model",
   * "gordon", "explicit_fade"). Surfaced to the user via the panel's
   * method-tag tooltip.
   */
  composite_intrinsic_value?: number | null
  composite_components?: {
    method?: string | null
    dcf_weight?: number | null
    multiples_weight?: number | null
    consensus_weight?: number | null
  } | null
  three_stage_fv?: number | null
  three_stage_method?: string | null
  ddm_fv?: number | null
  ddm_method?: string | null
  epv_per_share?: number | null
  liquidation_per_share?: number | null
  probability_weighted_fv?: number | null
  probability_weighted_method?: string | null
  /**
   * T5.3 (2026-06-10): 4 derived insights synthesized at the router
   * layer from the rich payload (composite IV + 5-pillar confidence
   * + Graham/Tobin anchors + per-sector backtest accuracy). Surfaced
   * as one bundle so the frontend renders a single panel above the
   * Valuation tab. Each of the four sub-slots is independently
   * nullable; the panel hides any card with a null slot. Backend
   * shape lives in backend/services/derived_insights_service.py;
   * consumers should import the matching TS types from
   * components/analysis/DerivedInsightsPanel.tsx so the contract
   * stays in one place.
   */
  derived_insights?: {
    confidence_summary?: unknown | null
    estimator_clustering?: unknown | null
    floor_ceiling?: unknown | null
    sector_calibration?: unknown | null
  } | null
  /**
   * Implied-Assumptions extension (2026-06-10) — AlphaSpread-style
   * "what does the market expect at the current price?" framing.
   * Mirrors backend/services/reverse_dcf_service.ImpliedAssumptionsResult.
   * Field-additive: legacy cached payloads predate the field; the
   * <ImpliedAssumptionsCard /> component hides itself when absent.
   */
  implied_assumptions?: {
    implied_revenue_cagr_pct: number
    implied_terminal_growth_pct: number
    implied_margin_expansion_bps: number | null
    implied_wacc_pct: number | null
    consensus_revenue_cagr_pct: number | null
    growth_gap_pp: number | null
    /** "modest" | "moderate" | "aggressive" | "extreme" */
    market_expectation_label: string
    /** 0-100 plausibility vs trailing 3y CAGR + sector tilt */
    plausibility_score: number
    /** One-line rendered headline, observational. */
    headline: string
  } | null
  /**
   * Cross-engine consensus signal (2026-06-10): direction-agreement
   * count across the 7+ standalone estimators (DCF, Multiples, Wall
   * Street, Three-stage, DDM, EPV, Probability-weighted). Populated
   * at the router boundary by `_inject_consensus_signal_*`. Distinct
   * from `composite_intrinsic_value` (weighted magnitude) and from
   * `derived_insights.estimator_clustering` (magnitude proximity);
   * this slot is the directional vote tally. Consumers should
   * import the matching TS types from
   * components/analysis/ConsensusSignalBadge.tsx so the contract
   * stays in one place. Optional + null on legacy cached payloads.
   */
  cross_engine_consensus?: {
    direction_agreement_count?: number
    total_estimators?: number
    direction_agreement_pct?: number
    magnitude_clustering_cv?: number | null
    consensus_level?: string
    consensus_direction?: string | null
    headline?: string
    sanity_warnings?: string[]
    estimator_breakdown?: unknown[]
  } | null
  /**
   * Backend-authored formula metadata, keyed by metric id (e.g.
   * "margin_of_safety", "roce"). Populated from
   * backend/services/analysis/formulas.py — the single source of
   * truth introduced after the 2026-04-25 MoS-tooltip drift bug.
   *
   * The MetricTooltip component prefers `formulas[key].formula` over
   * the hard-coded mirror in `lib/metric_explanations.ts`. Optional
   * because pre-PR cached payloads do not carry it.
   */
  formulas?: Record<string, FormulaInfo>
}

/**
 * Coverage Tier (feat/coverage-tier-system).
 *
 * Mirrors backend/services/coverage_tier_service.py. A 7-criteria rubric
 * collapses to a single A/B/C label so users can tell at a glance whether
 * we model a stock with full confidence (A), partial confidence (B), or
 * limited coverage (C). Labeling-only — never modifies FV or score.
 *
 * The full breakdown comes from GET /api/v1/coverage/{ticker}; the og-data
 * endpoint emits only the compact summary `{tier, criteria_met}`.
 */
export interface CoverageTierRubricItem {
  key: string
  label: string
  value: number | null
  threshold: number
  passed: boolean
}

export interface CoverageTier {
  tier: "A" | "B" | "C"
  criteria_met: string         // e.g. "5/7"
  criteria_passed?: number
  criteria_total?: number
  reasons?: string[]
  rubric?: CoverageTierRubricItem[]
  ticker?: string
}

export interface CoverageTierSummary {
  tier: "A" | "B" | "C"
  criteria_met: string
}

/**
 * Per-metric metadata block emitted by the backend on every
 * AnalysisResponse. Mirrors `backend/models/responses.py::FormulaInfo`.
 */
export interface FormulaInfo {
  key: string
  label: string
  formula: string
  explanation: string
  units?: string
  sector_note?: string | null
}

export interface ScreenerStock {
  ticker: string
  company_name: string
  score: number
  fair_value: number
  current_price: number
  margin_of_safety: number
  // Step B (2026-05-17): true Buffett MoS — see ValuationOutput note.
  buffett_mos_pct?: number | null
  verdict: string
  moat: string
  confidence: string
  sector: string
}

export interface ScreenerResponse {
  results: ScreenerStock[]
  total: number
  page: number
  page_size: number
  filter_applied: Record<string, unknown>
}

export interface MarketIndex {
  name: string
  price: number
  change_pct: number
  /**
   * 7 daily closes oldest→newest for the inline MarketsStrip sparkline
   * (2026-06-09 — feat/home-sparklines-everywhere). Empty array when
   * the backend has no `nse_index_history` rows for this tile (SENSEX,
   * synthetic indices, or fresh indices the ingestor hasn't backfilled
   * yet). Frontend treats empty as "skip the sparkline cell".
   */
  sparkline_7d?: number[]
}

export interface MarketPulseResponse {
  indices: MarketIndex[]
  fear_greed_index: number | null
  fear_greed_label: string | null
  timestamp: string
  // Macro extension — populated only with ?include_macro=true
  fii_net_cr?: number | null
  dii_net_cr?: number | null
  fii_date?: string | null
  fii_stale?: boolean
  usd_inr?: number | null
  // 24h % change for USD/INR vs previous trading day's close. Backed by
  // the same cached yfinance series that fills macro_sparklines.USDINR
  // — single source of truth, no extra round-trip. Optional + degrades
  // to null when the upstream fetch is rate-limited.
  usd_inr_change_pct?: number | null
  gold_usd?: number | null
  silver_usd?: number | null
  crude_usd?: number | null
  // 24h % change for commodities (2026-06-09 — feat/home-commodities-movers).
  gold_usd_change_pct?: number | null
  silver_usd_change_pct?: number | null
  crude_usd_change_pct?: number | null
  // INR display values (₹/10g) — server pre-converts gold and silver
  // from USD/oz so the MarketsStrip tile stays a dumb formatter.
  gold_inr_per_10g?: number | null
  silver_inr_per_10g?: number | null
  risk_free_pct?: number | null
  // 24h % change for the 10Y risk-free proxy. Same cached-series
  // pattern as usd_inr_change_pct above. Degrades to null gracefully.
  risk_free_change_pct?: number | null
  nifty_midcap_price?: number | null
  nifty_midcap_change_pct?: number | null
  ai_summary?: string | null
  /**
   * 7-day sparkline series for non-index tiles (USD/INR, India 10Y,
   * GOLD, SILVER, CRUDE). Optional + each key only present when the
   * macro ingest had ≥ 2 daily points. Frontend looks up by tile
   * slug ("USDINR", "GOLD", "SILVER", "CRUDE", "INDIA10Y"); a missing
   * key means the tile renders without a sparkline cell.
   */
  macro_sparklines?: Record<string, number[]> | null
}

// Today's Movers — top gainers / losers from a cohort (default NIFTY 500).
// Backed by /api/v1/market/today-movers, cached 60s server-side.
export interface TodayMover {
  ticker: string
  company_name: string
  change_pct: number
  close: number
  prev_close: number
}

export interface TodayMoversResponse {
  as_of: string | null
  gainers: TodayMover[]
  losers: TodayMover[]
  stale?: boolean
  cohort?: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user_id: string
  email: string
  tier: Tier
  analyses_today: number
  analysis_limit: number
  // Editable display name (PR #72) — null when never set;
  // frontend falls back to nameFromEmail() in PersonalHeader.
  display_name: string | null
  display_name_edits_remaining: number
  // Feature flags resolved server-side for this user. Optional because
  // pre-PR backends omit the field; useFeatureFlag() treats absence as
  // all-disabled.
  feature_flags?: Record<string, boolean>
  // Soft email-verify flag (feat/soft-email-verify-gates). Optional —
  // pre-PR backends omit it and the auth store defaults to true so the
  // banner doesn't pop spuriously.
  email_verified?: boolean
}

export interface UserResponse {
  user_id: string
  email: string
  tier: Tier
  analyses_today: number
  analysis_limit: number
  created_at: string
  display_name: string | null
  display_name_edits_remaining: number
  // See TokenResponse.feature_flags above.
  feature_flags?: Record<string, boolean>
  // See TokenResponse.email_verified above.
  email_verified?: boolean
}

// PATCH /api/v1/account/profile response shape.
export interface ProfileUpdateResponse {
  display_name: string
  edits_used: number
  edits_remaining: number
}

export interface HoldingResponse {
  ticker: string
  company_name: string
  entry_price: number
  current_price: number
  iv: number
  mos_pct: number
  signal: string
  sector: string
  notes: string
  saved_at: string
}

export interface PortfolioHealthResponse {
  score: number
  grade: string
  summary: string
  issues: string[]
  strengths: string[]
  overvalued_count: number
  undervalued_count: number
  danger_positions: string[]
  concentration_warning: string | null
}

export interface SectorOverviewItem {
  name: string
  avg_score: number
  pct_undervalued: number
  trend: string
}

export interface WatchlistItemResponse {
  ticker: string
  company_name: string
  added_price: number
  target_price: number
  alert_mos_threshold: number
  notes: string
  added_at: string
  // T6.5 — inline valuation slice already surfaced by the backend
  // GET /api/v1/watchlist/ endpoint (bulk JOIN against
  // analysis_cache). The fields are nullable because a missing
  // cache row is the dominant case for freshly-watchlisted tickers.
  fair_value?: number | null
  mos_pct?: number | null
  buffett_mos_pct?: number | null
  verdict?: string | null
  as_of?: string | null
}

export interface AlertResponse {
  id: number
  ticker: string
  alert_type: string
  target_price: number
  created_at: string
  is_active: boolean
}

export interface SuccessResponse {
  ok: boolean
  message: string
}

// ── Notifications (in-app bell + drawer) ─────────────────────
// Mirrors backend/services/notifications_service.py NotificationType
// and the row shape returned by the /api/v1/notifications/* routes.
export type NotificationType =
  | "alert_fired"
  | "portfolio_event"
  | "earnings_reminder"
  | "market_event"
  | "model_update"
  | "system"

export interface Notification {
  id: number
  type: NotificationType
  title: string
  body: string | null
  link: string | null
  metadata: Record<string, unknown>
  created_at: string  // ISO8601
  read_at: string | null
}

export interface NotificationsUnreadResponse {
  items: Notification[]
  count: number
}

export interface NotificationsRecentResponse {
  items: Notification[]
}

export interface NotificationsUnreadCountResponse {
  count: number
}

// ── Mutual Funds (Phase 3-slim) ──────────────────────────────────────
// Mirrors backend/models/fund.py response shapes. The fund detail page
// is intentionally read-only; no advisory / verdict-band fields exist
// on these types. Phase 2's returns + cost block is optional because
// it ships in a separate parallel PR.

export type FundRiskometerLevel =
  | "Low"
  | "LowToModerate"
  | "Moderate"
  | "ModeratelyHigh"
  | "High"
  | "VeryHigh"

export interface Fund {
  scheme_code: string
  isin_growth: string | null
  isin_div: string | null
  scheme_name: string
  amc: string
  plan: "Direct" | "Regular" | null
  option: "Growth" | "IDCW" | "IDCW-Reinvest" | null
  category: string | null
  sub_category: string | null
  benchmark_index_code: string | null
  inception_date: string | null
  riskometer_level: FundRiskometerLevel | null
  is_active: boolean
}

export interface FundNavPoint {
  nav_date: string
  nav: number
  aum_cr: number | null
}

export interface FundBenchmarkPoint {
  benchmark_index_code: string
  nav_date: string
  tri_value: number
}

export interface FundReturnsCache {
  ret_1y: number | null
  ret_3y: number | null
  ret_5y: number | null
  ret_10y: number | null
  ret_si: number | null
  cagr_3y: number | null
  cagr_5y: number | null
  ter_direct: number | null
  ter_regular: number | null
  yieldiq_fund_score: number | null
}

export interface FundDetailResponse {
  fund: Fund
  nav_history: FundNavPoint[]
  benchmark_history: FundBenchmarkPoint[]
  metrics: FundReturnsCache | null
}

export interface FundListItem {
  scheme_code: string
  scheme_name: string
  amc: string
  category: string | null
  sub_category: string | null
  riskometer_level: FundRiskometerLevel | null
  plan: "Direct" | "Regular" | null
}

export interface FundListResponse {
  funds: FundListItem[]
  total: number
}

// ── Phase 1 — Fair-Value History contract (Agent B) ──────────────
// Mirrors backend/models/fair_value_history.py exactly. Treat the
// shapes as locked: Agent A wires the data layer, Agent C builds the
// chart, Agent D writes the tests — all against this contract.
export type FVHistoryProvenance = "snapshot" | "golden" | "live"
export type FVAnnotationConfidence = "high" | "inferred" | "data_refresh"

export interface FairValueHistoryPoint {
  date: string                // ISO date, YYYY-MM-DD
  fair_value: number          // ₹ per share, base-case scenario
  bear_iv: number | null
  bull_iv: number | null
  scenario_weights: Record<string, number> | null
  model_version: string       // engine version slug at compute time
  provenance: FVHistoryProvenance
  manifest_id: string | null  // version_id of the linked manifest entry
}

export interface FairValueAnnotation {
  date: string                // ISO date, YYYY-MM-DD
  fv_delta_pct: number        // (this_fv - prev_fv) / prev_fv * 100
  manifest_id: string | null
  cause_label: string         // short neutral noun phrase, SEBI-clean
  confidence: FVAnnotationConfidence
}

export interface FairValueHistoryResponse {
  ticker: string
  points: FairValueHistoryPoint[]
  annotations: FairValueAnnotation[]
  starts_at: string | null    // ISO date of earliest point, or null
  points_count: number
  is_sparse: boolean          // true when series has < 3 points
}
