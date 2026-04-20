import type { HistoricalFinancialsResponse } from "@/lib/api"

interface Props {
  ticker: string
  data: HistoricalFinancialsResponse | null
}

// UNIT CONTRACT: backend /public/financials returns the raw Financials
// table rows, which are ALREADY stored in Crores by the XBRL ingestion
// pipeline (verified: RELIANCE FY25 pat=69648 == the reported ₹69,648 Cr
// headline). Do NOT divide again. If we ever ingest values in raw INR,
// flip this to 1e7.
const CR = 1

type RawGetter = (p: HistoricalFinancialsResponse["periods"][number]) => number | null

interface Row {
  label: string
  get: RawGetter
  // How to format the value once it's available (already normalised upstream).
  fmt: (v: number) => string
}

function crFmt(v: number): string {
  // ₹Cr with a sensible decimal budget
  if (Math.abs(v) >= 10000) return `\u20B9${(v / 1000).toFixed(1)}K Cr`
  if (Math.abs(v) >= 100) return `\u20B9${v.toFixed(0)} Cr`
  return `\u20B9${v.toFixed(1)} Cr`
}

function epsFmt(v: number): string {
  return `\u20B9${v.toFixed(2)}`
}

const ROWS: Row[] = [
  { label: "Revenue", get: p => p.revenue != null ? p.revenue / CR : null, fmt: crFmt },
  { label: "EBITDA", get: p => p.ebitda != null ? p.ebitda / CR : null, fmt: crFmt },
  { label: "EBIT", get: p => p.ebit != null ? p.ebit / CR : null, fmt: crFmt },
  { label: "PAT", get: p => p.pat != null ? p.pat / CR : null, fmt: crFmt },
  { label: "EPS (diluted)", get: p => p.eps_diluted, fmt: epsFmt },
  { label: "CFO", get: p => p.cfo != null ? p.cfo / CR : null, fmt: crFmt },
  { label: "CapEx", get: p => p.capex != null ? p.capex / CR : null, fmt: crFmt },
  { label: "FCF", get: p => p.free_cash_flow != null ? p.free_cash_flow / CR : null, fmt: crFmt },
  { label: "Total Assets", get: p => p.total_assets != null ? p.total_assets / CR : null, fmt: crFmt },
  { label: "Total Debt", get: p => p.total_debt != null ? p.total_debt / CR : null, fmt: crFmt },
  { label: "Shareholders' Equity", get: p => p.total_equity != null ? p.total_equity / CR : null, fmt: crFmt },
]

function cagr(first: number, last: number, years: number): number | null {
  if (!isFinite(first) || !isFinite(last) || years <= 0) return null
  // Need strictly positive start; CAGR is undefined if sign flips or start is 0
  if (first <= 0 || last <= 0) return null
  return (Math.pow(last / first, 1 / years) - 1) * 100
}

function Placeholder({ ticker }: { ticker: string }) {
  return (
    <section
      className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8"
      aria-label={`Historical financials for ${ticker}`}
    >
      <h2 className="text-lg font-bold text-gray-900 mb-1">Historical Financials</h2>
      <p className="text-sm text-gray-500">
        Historical financials for {ticker} are being prepared. Check back shortly for a
        5-year view of revenue, earnings, cash flow, and balance-sheet trends.
      </p>
    </section>
  )
}

export default function HistoricFinancialsTable({ ticker, data }: Props) {
  if (!data || !data.periods || data.periods.length === 0) {
    return <Placeholder ticker={ticker} />
  }

  // Take the last 5 periods sorted chronologically (oldest -> newest).
  // API doesn't guarantee order, so sort by period_end ascending.
  const sorted = [...data.periods].sort((a, b) => {
    const ax = a.period_end || ""
    const bx = b.period_end || ""
    return ax.localeCompare(bx)
  })
  const windowed = sorted.slice(-5)
  const years = windowed.map(p => (p.period_end || "").slice(0, 4) || "—")

  return (
    <section
      className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8 overflow-hidden"
      aria-label={`Historical financials for ${ticker}`}
    >
      <div className="mb-4">
        <h2 className="text-lg font-bold text-gray-900">Historical Financials</h2>
        <p className="text-xs text-gray-400">
          {ticker.toUpperCase()} &middot; Annual, last {windowed.length} year{windowed.length === 1 ? "" : "s"} &middot; amounts in &#8377;Cr unless noted
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-gray-500 border-b border-gray-200">
              <th className="text-left py-2 pr-3 font-semibold">Metric</th>
              {years.map((y, i) => (
                <th key={`${y}-${i}`} className="text-right py-2 px-2 font-semibold font-mono">
                  {y}
                </th>
              ))}
              <th className="text-right py-2 pl-3 font-semibold">CAGR</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map(row => {
              const values = windowed.map(p => row.get(p))
              const first = values.find(v => v != null) ?? null
              const last = [...values].reverse().find(v => v != null) ?? null
              const spanYears = windowed.length - 1
              const g = first != null && last != null ? cagr(first, last, spanYears) : null
              return (
                <tr key={row.label} className="border-b border-gray-100 last:border-0">
                  <td className="py-2 pr-3 text-gray-700 font-medium">{row.label}</td>
                  {values.map((v, i) => (
                    <td key={i} className="py-2 px-2 text-right font-mono text-gray-900 tabular-nums">
                      {v != null ? row.fmt(v) : "\u2014"}
                    </td>
                  ))}
                  <td className="py-2 pl-3 text-right">
                    {g != null ? (
                      <span
                        className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold tabular-nums ${
                          g >= 0
                            ? "bg-green-50 text-green-700 border border-green-100"
                            : "bg-red-50 text-red-700 border border-red-100"
                        }`}
                      >
                        {g >= 0 ? "+" : ""}
                        {g.toFixed(1)}%
                      </span>
                    ) : (
                      <span className="text-gray-300 text-xs">{"\u2014"}</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[10px] text-gray-400">
        CAGR computed across the visible window. Signs reverse if start value is zero or negative.
      </p>
    </section>
  )
}
