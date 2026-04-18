/**
 * dataFreshness — tiny util for rendering "N minutes ago" captions next
 * to Prism payloads. Used by the EditorialHero refresh badge and the
 * /about data-sources list.
 *
 * Format ladder:
 *   < 60s       → "just now"
 *   < 60m       → "{m}m ago"
 *   < 24h       → "{h}h ago"
 *   otherwise   → "{d}d ago"
 *
 * Returns null for invalid / unparseable input so callers can omit the
 * badge entirely rather than render "—" (per Trust-Surface spec).
 */
export function timeAgo(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  const t = d.getTime()
  if (!Number.isFinite(t)) return null
  const diffMs = Date.now() - t
  if (diffMs < 0) return "just now"
  if (diffMs < 60_000) return "just now"
  const m = Math.floor(diffMs / 60_000)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const days = Math.floor(h / 24)
  return `${days}d ago`
}
