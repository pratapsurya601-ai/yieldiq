/**
 * Breadcrumb — the small caps · letter-spaced pill row under the company
 * name on the analysis page:
 *
 *   NSE · Information Technology · Large Cap · NIFTY 50
 *
 * Day-41 (2026-05-20): exchange + sector + marketCapBucket are now
 * clickable links to faceted /stocks views. Drives internal crawl
 * graph + lets users discover peers. Pure server component.
 */
import Link from "next/link"

export type MarketCapBucket = "Large Cap" | "Mid Cap" | "Small Cap" | null

interface BreadcrumbProps {
  exchange: "NSE" | "BSE" | string
  sector: string
  marketCapBucket: MarketCapBucket
  /** Index memberships, e.g. ["NIFTY 50", "NIFTY BANK"]. */
  indices?: string[]
}

/** Map "NIFTY 50" → /nifty50, "NIFTY BANK" → /nifty-bank. */
function indexHref(idx: string): string | null {
  const k = idx.toUpperCase().replace(/\s+/g, "-")
  if (k === "NIFTY-50") return "/nifty50"
  if (k === "NIFTY-BANK") return "/nifty-bank"
  if (k === "NIFTY-IT") return "/nifty-it"
  return null
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
  // Day-41 (2026-05-20): every part now carries an optional `href`.
  // Exchange → /stocks?exchange=, sector → /stocks?sector=,
  // market-cap bucket → /stocks?cap=, NIFTY 50/Bank/IT → static
  // index landing pages. Pieces with no href fall back to a plain
  // <span> so the markup stays semantic.
  const parts: Array<{ text: string; href?: string; highlight?: boolean }> = []
  if (exchange) {
    parts.push({
      text: exchange,
      href: `/stocks?exchange=${exchange.toLowerCase()}`,
    })
  }
  if (sector) {
    parts.push({
      text: sector,
      href: `/stocks?sector=${encodeURIComponent(sector)}`,
    })
  }
  if (marketCapBucket) {
    parts.push({
      text: marketCapBucket,
      href: `/stocks?cap=${marketCapBucket.toLowerCase().replace(/\s+/g, "-")}`,
    })
  }
  // Highlight NIFTY 50 specifically — it's the membership that matters most.
  for (const idx of indices) {
    const href = indexHref(idx) ?? undefined
    parts.push({
      text: idx,
      href,
      highlight: idx.toUpperCase().includes("NIFTY 50"),
    })
  }

  if (parts.length === 0) return null

  return (
    <nav
      aria-label="Stock classification"
      data-testid="breadcrumb-classification"
      className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] uppercase tracking-[0.14em] text-caption"
    >
      {parts.map((p, i) => {
        const innerClass = p.highlight
          ? "inline-flex items-center rounded-full bg-[color:var(--color-success)]/10 text-success px-2 py-[2px] font-semibold tracking-[0.12em]"
          : "font-medium hover:text-ink hover:underline focus:underline focus:outline-none"
        const inner = p.href ? (
          <Link href={p.href} className={innerClass}>
            {p.text}
          </Link>
        ) : (
          <span className={innerClass}>{p.text}</span>
        )
        return (
          <span key={`${p.text}-${i}`} className="flex items-center gap-2">
            {i > 0 && <span aria-hidden className="text-border">·</span>}
            {inner}
          </span>
        )
      })}
    </nav>
  )
}
