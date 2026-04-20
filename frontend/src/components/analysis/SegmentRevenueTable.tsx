// frontend/src/components/analysis/SegmentRevenueTable.tsx
// Server Component — renders segment-level revenue across years.
// Fetches from /api/v1/public/segments/{ticker}. Renders nothing
// when the company doesn't disclose segments (graceful degrade).

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

interface SegmentPoint {
  period_end: string | null
  revenue_cr: number
}

interface SegmentSeries {
  name: string
  points: SegmentPoint[]
}

interface SegmentResponse {
  ticker: string
  display_ticker: string
  years: number
  segments: SegmentSeries[]
}

async function fetchSegments(ticker: string, years: number): Promise<SegmentResponse | null> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/public/segments/${ticker}?years=${years}`,
      { next: { revalidate: 3600 } },
    )
    if (!res.ok) return null
    return (await res.json()) as SegmentResponse
  } catch {
    return null
  }
}

function fmtPeriod(iso: string | null): string {
  if (!iso) return "\u2014"
  try {
    const d = new Date(iso)
    return `FY${String(d.getFullYear()).slice(-2)}`
  } catch {
    return iso
  }
}

function fmtCr(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "\u2014"
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}K`
  return n.toFixed(0)
}

interface Props {
  ticker: string
  years?: number
}

export default async function SegmentRevenueTable({ ticker, years = 5 }: Props) {
  const data = await fetchSegments(ticker, years)
  if (!data || !data.segments || data.segments.length === 0) {
    return null
  }

  // Build a sorted union of all period_end values across segments.
  const periodSet = new Set<string>()
  for (const s of data.segments) {
    for (const p of s.points) {
      if (p.period_end) periodSet.add(p.period_end)
    }
  }
  const periods = Array.from(periodSet).sort()
  if (periods.length === 0) return null

  // Index revenue by segment + period for O(1) lookup in render.
  const lookup = new Map<string, Map<string, number>>()
  for (const s of data.segments) {
    const m = new Map<string, number>()
    for (const p of s.points) {
      if (p.period_end) m.set(p.period_end, p.revenue_cr)
    }
    lookup.set(s.name, m)
  }

  return (
    <section
      className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8"
      aria-label={`Segment revenue for ${ticker}`}
    >
      <h2 className="text-lg font-bold text-gray-900 mb-1">Segment Revenue</h2>
      <p className="text-xs text-gray-400 mb-4">
        Business-segment revenue parsed from XBRL filings &middot; in &#8377; Cr
      </p>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200">
              <th className="text-left py-2 pr-4 font-semibold text-gray-600">Segment</th>
              {periods.map(p => (
                <th
                  key={p}
                  className="text-right py-2 px-3 font-semibold text-gray-600 font-mono"
                >
                  {fmtPeriod(p)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.segments.map(seg => (
              <tr key={seg.name} className="border-b border-gray-100">
                <td className="py-2 pr-4 font-medium text-gray-900">{seg.name}</td>
                {periods.map(p => {
                  const v = lookup.get(seg.name)?.get(p)
                  return (
                    <td
                      key={p}
                      className="text-right py-2 px-3 text-gray-700 font-mono"
                    >
                      {v == null ? "\u2014" : fmtCr(v)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-gray-400 mt-3">
        Source: company XBRL filings (BSE). Segment definitions are
        company-defined and may change between years.
      </p>
    </section>
  )
}
