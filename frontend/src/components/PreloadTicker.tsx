"use client"
// Preload hint for a ticker's PRISM analysis response. Placed anywhere in
// the React tree — Next 16 hoists <link> elements into <head>.
//
// Why prism and not /analysis/: the /prism/:ticker endpoint is public
// (no Authorization header required), so it's safe to preload without
// credentials. The subsequent fetch from the analysis page reuses the
// preloaded response from the HTTP cache.
//
// Only preload ONE ticker per page — more than one saturates the
// connection and starves LCP resources.
const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export default function PreloadTicker({ ticker }: { ticker: string }) {
  if (!ticker) return null
  const href = `${API_BASE}/api/v1/prism/${encodeURIComponent(ticker)}`
  return (
    <link
      rel="preload"
      as="fetch"
      href={href}
      crossOrigin="anonymous"
    />
  )
}
