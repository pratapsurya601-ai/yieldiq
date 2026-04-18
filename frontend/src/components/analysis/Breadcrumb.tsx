/**
 * Breadcrumb — the small caps · letter-spaced pill row under the company
 * name on the analysis page:
 *
 *   NSE · Information Technology · Large Cap · NIFTY 50
 *
 * Pure server component. Takes resolved data from the parent page.
 */

export type MarketCapBucket = "Large Cap" | "Mid Cap" | "Small Cap" | null

interface BreadcrumbProps {
  exchange: "NSE" | "BSE" | string
  sector: string
  marketCapBucket: MarketCapBucket
  /** Index memberships, e.g. ["NIFTY 50", "NIFTY BANK"]. */
  indices?: string[]
}

/**
 * Derive bucket from market cap in crores. Thresholds follow the
 * standard SEBI cut-offs used across YieldIQ:
 *   > 50,000 Cr → Large Cap
 *   10,000 – 50,000 Cr → Mid Cap
 *   < 10,000 Cr → Small Cap
 * Returns null for missing / non-positive values so the pill is omitted
 * rather than showing a misleading bucket.
 */
export function bucketFromMarketCapCr(cr: number | null | undefined): MarketCapBucket {
  if (cr === null || cr === undefined || !Number.isFinite(cr) || cr <= 0) return null
  if (cr > 50_000) return "Large Cap"
  if (cr >= 10_000) return "Mid Cap"
  return "Small Cap"
}

export default function Breadcrumb({
  exchange,
  sector,
  marketCapBucket,
  indices = [],
}: BreadcrumbProps) {
  const parts: Array<{ text: string; highlight?: boolean }> = []
  if (exchange) parts.push({ text: exchange })
  if (sector) parts.push({ text: sector })
  if (marketCapBucket) parts.push({ text: marketCapBucket })
  // Highlight NIFTY 50 specifically — it's the membership that matters most.
  for (const idx of indices) {
    parts.push({ text: idx, highlight: idx.toUpperCase().includes("NIFTY 50") })
  }

  if (parts.length === 0) return null

  return (
    <nav
      aria-label="Stock classification"
      className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] uppercase tracking-[0.14em] text-caption"
    >
      {parts.map((p, i) => (
        <span key={`${p.text}-${i}`} className="flex items-center gap-2">
          {i > 0 && <span aria-hidden className="text-border">·</span>}
          {p.highlight ? (
            <span className="inline-flex items-center rounded-full bg-[color:var(--color-success)]/10 text-success px-2 py-[2px] font-semibold tracking-[0.12em]">
              {p.text}
            </span>
          ) : (
            <span className="font-medium">{p.text}</span>
          )}
        </span>
      ))}
    </nav>
  )
}
