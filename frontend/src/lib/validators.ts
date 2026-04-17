// frontend/src/lib/validators.ts
// ═══════════════════════════════════════════════════════════════
// PRE-RENDER SANITY GATES
//
// Last line of defense before showing financial data to users.
// Better to hide a field than show "WACC 1200%" or "Fair Value 4x CMP".
//
// Convention: backend returns rates as DECIMALS (0.12 for 12%).
// Frontend multiplies by 100 only at render time.
// ═══════════════════════════════════════════════════════════════

export interface AnalysisDataLike {
  valuation?: {
    fair_value?: number
    current_price?: number
    margin_of_safety?: number
    wacc?: number
    terminal_growth?: number
    fcf_growth_rate?: number
    confidence_score?: number
  }
  quality?: {
    yieldiq_score?: number
    roe?: number | null
    de_ratio?: number | null
    piotroski_score?: number
    moat?: string
  }
}

export interface ValidationResult {
  ok: boolean
  severity: "ok" | "warning" | "critical"
  issues: string[]
  hideFields: Set<string>  // field names to hide from display
  bannerMessage: string | null
}

const FIELDS = {
  WACC: "wacc",
  ROE: "roe",
  FAIR_VALUE: "fair_value",
  MOS: "margin_of_safety",
  DE_RATIO: "de_ratio",
  CONFIDENCE: "confidence",
  TERMINAL_GROWTH: "terminal_growth",
  FCF_GROWTH: "fcf_growth_rate",
} as const

/**
 * Validate analysis data against hard rules.
 * If ANY critical rule fails, hide all valuation fields and show banner.
 */
export function validateAnalysisData(data: AnalysisDataLike): ValidationResult {
  const issues: string[] = []
  const hideFields = new Set<string>()
  let critical = false

  const v = data.valuation || {}
  const q = data.quality || {}

  // ── HARD BOUNDS (decimal convention: WACC 0.03-0.30) ────────
  if (v.wacc !== undefined && v.wacc !== null) {
    if (v.wacc < 0.02 || v.wacc > 0.30) {
      issues.push(`WACC out of bounds: ${(v.wacc * 100).toFixed(1)}% (expected 2%-30%)`)
      hideFields.add(FIELDS.WACC)
      hideFields.add(FIELDS.FAIR_VALUE)
      hideFields.add(FIELDS.MOS)
      critical = true
    }
  }

  // Terminal growth: 0% to 6%
  if (v.terminal_growth !== undefined && v.terminal_growth !== null) {
    if (v.terminal_growth < 0 || v.terminal_growth > 0.08) {
      issues.push(`Terminal growth out of bounds: ${(v.terminal_growth * 100).toFixed(1)}%`)
      hideFields.add(FIELDS.TERMINAL_GROWTH)
      critical = true
    }
  }

  // FCF growth rate: -30% to +60%
  if (v.fcf_growth_rate !== undefined && v.fcf_growth_rate !== null) {
    if (v.fcf_growth_rate < -0.50 || v.fcf_growth_rate > 0.80) {
      issues.push(`FCF growth out of bounds: ${(v.fcf_growth_rate * 100).toFixed(1)}%`)
      hideFields.add(FIELDS.FCF_GROWTH)
      critical = true
    }
  }

  // Margin of safety: -95% to +500%
  if (v.margin_of_safety !== undefined && v.margin_of_safety !== null) {
    if (v.margin_of_safety < -95 || v.margin_of_safety > 500) {
      issues.push(`MoS out of bounds: ${v.margin_of_safety.toFixed(1)}%`)
      hideFields.add(FIELDS.MOS)
      hideFields.add(FIELDS.FAIR_VALUE)
      critical = true
    }
  }

  // Fair value vs CMP ratio: 0.2x to 5x
  if (v.fair_value && v.current_price && v.current_price > 0) {
    const ratio = v.fair_value / v.current_price
    if (ratio > 5 || ratio < 0.2) {
      issues.push(`Fair value ${ratio.toFixed(1)}x CMP — extreme ratio, likely data quality issue`)
      hideFields.add(FIELDS.FAIR_VALUE)
      hideFields.add(FIELDS.MOS)
      critical = true
    }
  }

  // ── ROE: percentage convention (-100 to +100) ───────────────
  if (q.roe !== null && q.roe !== undefined) {
    if (q.roe < -100 || q.roe > 200) {
      issues.push(`ROE out of bounds: ${q.roe.toFixed(1)}%`)
      hideFields.add(FIELDS.ROE)
    }
  }

  // ── D/E: 0 to 20 ──────────────────────────────────────────────
  if (q.de_ratio !== null && q.de_ratio !== undefined) {
    if (q.de_ratio < 0 || q.de_ratio > 20) {
      issues.push(`Debt/Equity out of bounds: ${q.de_ratio.toFixed(2)}`)
      hideFields.add(FIELDS.DE_RATIO)
    }
  }

  // ── Score: 0 to 100 ───────────────────────────────────────────
  if (q.yieldiq_score !== undefined && q.yieldiq_score !== null) {
    if (q.yieldiq_score < 0 || q.yieldiq_score > 100) {
      issues.push(`YieldIQ score out of bounds: ${q.yieldiq_score}`)
      critical = true
    }
  }

  // ── CROSS-FIELD CONSISTENCY ──────────────────────────────────

  // Wide moat + ROE < 10% = contradiction
  if (q.moat === "Wide" && q.roe !== null && q.roe !== undefined && q.roe < 10) {
    issues.push(`Wide moat with ROE only ${q.roe.toFixed(1)}% — inconsistent`)
  }

  // High Piotroski + High debt = unusual
  if (q.piotroski_score && q.piotroski_score >= 7 && q.de_ratio && q.de_ratio > 2) {
    issues.push(`High Piotroski (${q.piotroski_score}/9) with D/E ${q.de_ratio.toFixed(2)} — review`)
  }

  // FV >> CMP + High confidence = needs review
  if (
    v.fair_value && v.current_price && v.confidence_score &&
    v.fair_value / v.current_price > 3 &&
    v.confidence_score > 70
  ) {
    issues.push(`Fair value ${(v.fair_value / v.current_price).toFixed(1)}x CMP with ${v.confidence_score}% confidence — review`)
  }

  const ok = issues.length === 0
  const severity = critical ? "critical" : (issues.length > 0 ? "warning" : "ok")

  let bannerMessage: string | null = null
  if (critical) {
    bannerMessage = "Some valuation figures for this stock are being recalibrated. Hidden fields will return after data review."
  } else if (issues.length > 0) {
    bannerMessage = "Data quality observations on this stock — see hidden fields below."
  }

  return { ok, severity, issues, hideFields, bannerMessage }
}

/**
 * Quick check: does this look like a USD-reporting Indian stock
 * whose financials might be wrong? (Falls back to yfinance on backend)
 */
export function isUSDReporter(ticker: string): boolean {
  const usd = new Set([
    "INFY", "WIPRO", "HCLTECH", "TECHM", "MPHASIS",
    "HEXAWARE", "LTIM", "PERSISTENT", "COFORGE",
    "TATAELXSI", "CYIENT", "ZENSAR", "MASTEK", "OFSS",
    "DIVISLAB", "LAURUSLABS",
  ])
  const clean = ticker.replace(/\.NS$|\.BO$/i, "").toUpperCase()
  return usd.has(clean)
}
