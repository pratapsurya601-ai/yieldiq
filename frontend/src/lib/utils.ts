import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// YieldIQ is India-only. Default to INR / \u20b9 for null, "", "inr",
// and any unrecognised currency tag (incl. the v50 yfinance mis-tag
// where Indian listings come through as "USD"). Only an explicit
// foreign currency code falls into the non-INR branch.
// See `lib/currency.ts` for the canonical symbol/locale helpers.
const NON_INR_CURRENCIES = new Set(["USD", "EUR", "GBP", "JPY", "CNY", "SGD", "HKD", "AUD", "CAD", "CHF"])

// Defense in depth (2026-05-02): even after backend fix 9093652
// (CAPLIPOINT bare-ticker → currency='USD'), the frontend should
// never render '$' on a ticker that's clearly an Indian listing.
// The bare-ticker bug class can re-emerge from any new backend code
// path that constructs a Stock without consulting the canonical
// ticker_classifier. Force INR when the ticker suffix says so.
const INDIAN_SUFFIXES = [".NS", ".BO", ".IN"]

function isIndianTicker(ticker?: string | null): boolean {
  if (!ticker) return false
  const upper = ticker.toUpperCase()
  return INDIAN_SUFFIXES.some(s => upper.endsWith(s))
}

export function formatCurrency(value: number, currency?: string | null, ticker?: string | null): string {
  const abs = Math.abs(value)
  // Ticker-based override wins over backend currency tag.
  const effectiveCurrency = isIndianTicker(ticker)
    ? "INR"
    : (currency || "INR")
  const upper = effectiveCurrency.toUpperCase().trim()
  if (!NON_INR_CURRENCIES.has(upper)) {
    // INR (default) \u2014 covers null, undefined, "", "inr", "INR", "Rs", junk
    if (abs >= 1e7) return `\u20b9${(value / 1e7).toFixed(1)}Cr`
    if (abs >= 1e5) return `\u20b9${(value / 1e5).toFixed(1)}L`
    return `\u20b9${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`
  }
  // Explicit non-INR (rare on YieldIQ \u2014 only ADR cross-listings, etc.)
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(1)}M`
  return `$${value.toLocaleString("en-US", { maximumFractionDigits: 2 })}`
}

// P0-#3 (2026-04-22): clamp MoS at +/-100%. Backend widens/narrows the
// validator range for storage, but the UI must never render implausible
// "+164%"-style values that break user trust on micro-caps where the
// DCF denominator blows up. Out-of-band values render as ">=100.0%" /
// "<=-100.0%" with a single-source-of-truth clamp here.
export function formatMoS(mos: number): string {
  if (!Number.isFinite(mos)) return "—"
  if (mos >= 100) return "\u2265100.0%"
  if (mos <= -100) return "\u2264-100.0%"
  return `${mos >= 0 ? "+" : ""}${mos.toFixed(1)}%`
}

export function formatPct(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`
}

/**
 * Format a rate expressed as a DECIMAL (0.12) for display as percentage (12.0%).
 * Canonical helper — use this everywhere that takes wacc/terminal_growth/
 * fcf_growth_rate from the backend.
 *
 * Convention (documented in CLAUDE.md):
 *   Backend returns WACC, terminal_growth, fcf_growth_rate as DECIMALS.
 *   Frontend multiplies by 100 ONLY at render time via this helper.
 */
export function formatRateDecimal(value: number | null | undefined, decimals = 1): string {
  if (value == null || isNaN(value)) return "\u2014"
  return `${(value * 100).toFixed(decimals)}%`
}

/**
 * Format a value that's already in PERCENTAGE form (23.5 → "23.5%").
 * Use for ROE, ROCE which backend normalizes to percentage via _normalize_pct.
 */
export function formatPercentage(value: number | null | undefined, decimals = 1): string {
  if (value == null || isNaN(value)) return "\u2014"
  return `${value.toFixed(decimals)}%`
}

/**
 * Day-35 (2026-05-20): canonical number formatter for raw scalars that
 * aren't rupee amounts (e.g. P/E ratios, ROCE multiples, share counts).
 * Replaces 3+ local fmtNum() re-implementations across the app
 * (PeerComparisonCard, admin/story-dcf, etc.) that diverged on the
 * default decimal precision (1 dp vs 2 dp) and em-dash fallback.
 *
 * Use formatCurrency for rupee amounts (handles Cr/L compaction) and
 * formatPercentage for already-% values.
 */
export function formatNumberWithSuffix(
  value: number | null | undefined,
  decimals = 1,
  suffix = "",
): string {
  if (value == null || !Number.isFinite(value)) return "\u2014"
  return `${value.toFixed(decimals)}${suffix}`
}

/**
 * Day-35 (2026-05-20): signed-percentage formatter with explicit '+'
 * on positives. Replaces fmtPct() variants in PeerComparisonCard etc.
 * that diverged on the leading-sign convention.
 */
export function formatPctSigned(
  value: number | null | undefined,
  decimals = 1,
): string {
  if (value == null || !Number.isFinite(value)) return "\u2014"
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}%`
}

/**
 * Canonical MoS → verdict label.
 *
 * Single source of truth for the user-facing valuation verdict on
 * /analysis/[ticker]. Both the browser tab title (set in layout.tsx
 * generateMetadata and AnalysisBody useEffect) AND the on-page hero
 * headline / region caption MUST derive from this helper so the tab
 * and body can never disagree.
 *
 * Launch-day fix (2026-04-30): HDFCBANK shipped with tab="Undervalued"
 * but body="Above Fair Value" (MoS -12.3%) because the tab title was
 * derived from the backend `verdict` STRING (which can lag MoS during
 * cold-cache or stale-cache conditions) while the body was deriving
 * its label by other means. Funnel everything through MoS — the number
 * the user sees on screen — so sign-of-MoS and verdict can never
 * contradict.
 *
 * MoS is the SIGNED percentage (e.g. -12.3 means price is 12.3% above
 * fair value). NOT a decimal.
 */
export function verdictFromMos(mos: number | null | undefined): string {
  if (mos == null || !Number.isFinite(mos)) return "Fairly Valued"
  if (mos >= 25) return "Notably Undervalued"
  if (mos >= 5) return "Undervalued"
  if (mos > -5) return "Fairly Valued"
  if (mos > -25) return "Overvalued"
  return "Notably Overvalued"
}

/**
 * Day-91 (2026-05-22): verdict-pill confidence gate — single source of truth.
 *
 * Audit #4 found the Day-61 confidence gate (AnalysisHero only) was firing
 * inconsistently because FOUR render paths each derived their verdict
 * independently:
 *   - AnalysisHero  (Day-61 gate, threshold 50)
 *   - EditorialHero (score100 < 50 gate, no confidence check)
 *   - AnalysisBody  document.title (verdictFromMos only, no gate)
 *   - PublicAnalysis pill          (verdictFromMos only, no gate)
 *
 * Result: TCS rendered "NOTABLY UNDERVALUED" in the title bar alongside a
 * Data Limited banner; RELIANCE / INDIGO at 41-45% confidence rendered
 * confident "UNDERVALUED" pills. Audit guidance: route every label
 * through ONE gate function, raise threshold 50 -> 60, and add a
 * scenario-band-ratio gate so wide-band names also collapse to neutral.
 *
 * The gate fires when ANY of these is true:
 *   - dataLimited === true
 *   - confidence < 60 (was 50)
 *   - (bull_case - bear_case) / current_price > 0.25
 *
 * Returns true when the caller renders an "Under Review" /
 * "Low Confidence" label instead of a directional verdict.
 */
export const LOW_CONFIDENCE_THRESHOLD = 60
export const WIDE_BAND_RATIO_THRESHOLD = 0.25

export interface VerdictGateInputs {
  dataLimited?: boolean | null
  confidence?: number | null
  currentPrice?: number | null
  bullCase?: number | null
  bearCase?: number | null
}

export function shouldGateVerdict(inputs: VerdictGateInputs): boolean {
  const { dataLimited, confidence, currentPrice, bullCase, bearCase } = inputs
  if (dataLimited === true) return true
  if (
    typeof confidence === "number" &&
    Number.isFinite(confidence) &&
    confidence < LOW_CONFIDENCE_THRESHOLD
  ) {
    return true
  }
  if (
    typeof currentPrice === "number" &&
    currentPrice > 0 &&
    typeof bullCase === "number" &&
    Number.isFinite(bullCase) &&
    typeof bearCase === "number" &&
    Number.isFinite(bearCase)
  ) {
    const band = bullCase - bearCase
    const ratio = band / currentPrice
    if (Number.isFinite(ratio) && ratio > WIDE_BAND_RATIO_THRESHOLD) {
      return true
    }
  }
  return false
}

/**
 * SEBI-safe verdict display label.
 *
 * Loosened 2026-05-17: descriptive valuation vocabulary ("Undervalued"
 * / "Overvalued" / "Fairly Valued") is model output, not advice. Every
 * Indian valuation product surfaces these. The ModelDisclaimer carries
 * the "not a SEBI-registered IA" framing; imperative recommendations
 * remain banned via check_sebi_words.py. Legacy advisory wire-format
 * aliases are handled by lib/verdict.ts::verdictLabel.
 */
export function verdictDisplayLabel(v: string): string {
  if (!v) return ""
  const key = v.toLowerCase().replace(/\s+/g, "_")
  const map: Record<string, string> = {
    undervalued: "Undervalued",
    fairly_valued: "Fairly Valued",
    overvalued: "Overvalued",
    avoid: "Model Caveat",
    data_limited: "Insufficient Data",
    under_review: "Under Review",
    unavailable: "Unavailable",
  }
  if (map[key]) return map[key]
  // Fallback: title-case the key
  return key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())
}

/**
 * Region caption derived from the canonical Verdict value.
 *
 * Used by the EditorialHero small caption directly below the Prism dot —
 * a one-line region label that stays in lockstep with verdictDisplayLabel
 * so the headline and the caption can never disagree (the RELIANCE
 * triple-contradiction bug was caused by hero/tab/region each computing
 * their own label from a different field).
 */
export function verdictRegion(v: string): string {
  if (!v) return "Fairly Valued"
  const key = v.toLowerCase().replace(/\s+/g, "_")
  const map: Record<string, string> = {
    undervalued: "Undervalued",
    fairly_valued: "Fairly Valued",
    overvalued: "Overvalued",
    avoid: "Model Caveat",
    data_limited: "Insufficient Data",
    under_review: "Under Review",
    unavailable: "Unavailable",
  }
  return map[key] ?? "Fairly Valued"
}

const COMPANY_NAME_OVERRIDES: Record<string, string> = {
  "ITC.NS": "ITC Limited",
  "TCS.NS": "Tata Consultancy Services",
  "HDFCBANK.NS": "HDFC Bank",
  "BAJFINANCE.NS": "Bajaj Finance",
  "HINDUNILVR.NS": "Hindustan Unilever",
  "MARUTI.NS": "Maruti Suzuki India",
  "TITAN.NS": "Titan Company",
  "INFY.NS": "Infosys",
  "SBIN.NS": "State Bank of India",
  "ICICIBANK.NS": "ICICI Bank",
  "KOTAKBANK.NS": "Kotak Mahindra Bank",
  "AXISBANK.NS": "Axis Bank",
  "LT.NS": "Larsen & Toubro",
  "SUNPHARMA.NS": "Sun Pharmaceutical Industries",
  "NTPC.NS": "NTPC Limited",
  "ONGC.NS": "ONGC Limited",
  "RELIANCE.NS": "Reliance Industries",
  "WIPRO.NS": "Wipro Limited",
  "TATAMOTORS.NS": "Tata Motors",
  "ITC LIMITED": "ITC Limited",
}

const COMPANY_ABBREVIATIONS: Record<string, string> = {
  LT: "Ltd",
  LTD: "Ltd",
  SERV: "Services",
  IND: "Industries",
  CORP: "Corporation",
  TECH: "Technologies",
  PHARMA: "Pharma",
  FIN: "Finance",
  INF: "Infrastructure",
  CONS: "Consultancy",
  ENT: "Enterprises",
  INTL: "International",
  MFG: "Manufacturing",
  GRP: "Group",
  HLD: "Holdings",
  HLDG: "Holdings",
  CHEM: "Chemicals",
  ENGG: "Engineering",
  ELEC: "Electricals",
  AUTO: "Automobiles",
  RLWY: "Railway",
  PETRO: "Petroleum",
}

export function formatCompanyName(name: string, ticker?: string): string {
  if (!name) return name
  // Check overrides by ticker first
  if (ticker && COMPANY_NAME_OVERRIDES[ticker]) return COMPANY_NAME_OVERRIDES[ticker]
  // Check overrides by raw name
  if (COMPANY_NAME_OVERRIDES[name]) return COMPANY_NAME_OVERRIDES[name]
  // Already looks properly formatted (has lowercase letters)
  if (/[a-z]/.test(name)) return name
  return name
    .split(/\s+/)
    .map((word) => {
      const upper = word.toUpperCase()
      if (COMPANY_ABBREVIATIONS[upper]) return COMPANY_ABBREVIATIONS[upper]
      if (upper.length <= 2 && /^[A-Z&]+$/.test(upper)) return upper // keep short abbrevs like "IT", "&"
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
    })
    .join(" ")
}

/**
 * Absolute short-form date for <FreshnessStamp />. Renders "Mar 2024"
 * for historical filings. Caller prepends a label ("Latest filing: ...").
 * Returns "" for unparseable input so callers can collapse the stamp.
 */
export function formatAbsoluteShort(input: string | Date): string {
  const d = input instanceof Date ? input : new Date(input)
  const t = d.getTime()
  if (!Number.isFinite(t)) return ""
  return d.toLocaleDateString("en-IN", { month: "short", year: "numeric" })
}

/**
 * Relative-time formatter used by <FreshnessStamp />. Compact forms
 * designed to sit inline in the 11px caption without wrapping:
 *   < 60s   → "just now"
 *   < 60m   → "{n}m ago"
 *   < 24h   → "{n}h ago"
 *   < 7d    → "{n}d ago"
 *   beyond  → falls back to formatAbsoluteShort
 *
 * Future timestamps (negative diff, from clock skew) collapse to
 * "just now" so the UI never renders "in 2h" on an analysis card.
 */
export function formatRelativeTime(input: string | Date): string {
  const d = input instanceof Date ? input : new Date(input)
  const t = d.getTime()
  if (!Number.isFinite(t)) return ""
  const diffMs = Date.now() - t
  if (diffMs < 60_000) return "just now"
  const m = Math.floor(diffMs / 60_000)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const days = Math.floor(h / 24)
  if (days < 7) return `${days}d ago`
  return formatAbsoluteShort(d)
}
