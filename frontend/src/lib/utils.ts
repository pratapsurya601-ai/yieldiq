import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatCurrency(value: number, currency: string = "INR"): string {
  const abs = Math.abs(value)
  if (currency === "INR") {
    if (abs >= 1e7) return `\u20b9${(value / 1e7).toFixed(1)}Cr`
    if (abs >= 1e5) return `\u20b9${(value / 1e5).toFixed(1)}L`
    return `\u20b9${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`
  }
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
 * SEBI-safe verdict display label.
 * Maps internal verdict keys to user-facing text that is purely
 * descriptive (no imperative advice like "Avoid").
 */
export function verdictDisplayLabel(v: string): string {
  if (!v) return ""
  const key = v.toLowerCase().replace(/\s+/g, "_")
  const map: Record<string, string> = {
    undervalued: "Undervalued",
    fairly_valued: "Fairly valued",
    overvalued: "Overvalued",
    avoid: "High Risk",
    data_limited: "Data Limited",
    unavailable: "Unavailable",
  }
  if (map[key]) return map[key]
  // Fallback: title-case the key
  return key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())
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
