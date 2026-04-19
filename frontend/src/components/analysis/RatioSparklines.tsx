import type { RatioHistoryResponse, RatioHistoryPeriod } from "@/lib/api"

interface Props {
  ticker: string
  data: RatioHistoryResponse | null
}

type Key = keyof RatioHistoryPeriod

interface RatioSpec {
  label: string
  key: Key
  suffix: string
  decimals: number
}

const RATIOS: RatioSpec[] = [
  { label: "ROE", key: "roe", suffix: "%", decimals: 1 },
  { label: "ROCE", key: "roce", suffix: "%", decimals: 1 },
  { label: "Operating Margin", key: "operating_margin", suffix: "%", decimals: 1 },
  { label: "Debt / Equity", key: "de_ratio", suffix: "\u00D7", decimals: 2 },
  { label: "PE", key: "pe_ratio", suffix: "\u00D7", decimals: 1 },
  { label: "EV / EBITDA", key: "ev_ebitda", suffix: "\u00D7", decimals: 1 },
]

function fmt(val: number | null | undefined, suffix: string, decimals: number): string {
  if (val == null || isNaN(val)) return "\u2014"
  return `${val.toFixed(decimals)}${suffix}`
}

function Sparkline({ points }: { points: number[] }) {
  // Fixed viewBox — we draw into 0..100 x 0..30 and let CSS size it.
  const W = 100
  const H = 30
  if (points.length === 0) {
    return (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-8" aria-hidden="true">
        <line x1="0" y1={H / 2} x2={W} y2={H / 2} stroke="#e5e7eb" strokeDasharray="2 3" />
      </svg>
    )
  }
  if (points.length === 1) {
    // Just a dot in the middle
    return (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-8" aria-hidden="true">
        <circle cx={W / 2} cy={H / 2} r="2.5" fill="#2563eb" />
      </svg>
    )
  }
  const min = Math.min(...points)
  const max = Math.max(...points)
  const range = max - min || 1
  const coords = points.map((p, i) => {
    const x = (i / (points.length - 1)) * W
    const y = H - ((p - min) / range) * H
    return `${x.toFixed(2)},${y.toFixed(2)}`
  })
  const last = points[points.length - 1]
  const first = points[0]
  const trendUp = last >= first
  const stroke = trendUp ? "#16a34a" : "#dc2626"
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-8" preserveAspectRatio="none" aria-hidden="true">
      <polyline
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={coords.join(" ")}
        vectorEffect="non-scaling-stroke"
      />
      {/* End-cap dot for latest value */}
      <circle
        cx={coords[coords.length - 1].split(",")[0]}
        cy={coords[coords.length - 1].split(",")[1]}
        r="1.8"
        fill={stroke}
      />
    </svg>
  )
}

function Placeholder({ ticker }: { ticker: string }) {
  return (
    <section
      className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8"
      aria-label={`Ratio trends for ${ticker}`}
    >
      <h2 className="text-lg font-bold text-gray-900 mb-1">Ratio Trends</h2>
      <p className="text-sm text-gray-500">
        Historical ratio trends for {ticker} are being prepared. Once ready, this section
        will show multi-year trajectories of ROE, ROCE, margins, leverage, and valuation
        multiples.
      </p>
    </section>
  )
}

export default function RatioSparklines({ ticker, data }: Props) {
  if (!data || !data.periods || data.periods.length === 0) {
    return <Placeholder ticker={ticker} />
  }

  // Oldest -> newest so sparkline reads left-to-right chronologically.
  const sorted = [...data.periods].sort((a, b) => {
    const ax = a.period_end || ""
    const bx = b.period_end || ""
    return ax.localeCompare(bx)
  })
  const windowed = sorted.slice(-10)

  return (
    <section
      className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8"
      aria-label={`Ratio trends for ${ticker}`}
    >
      <div className="mb-4">
        <h2 className="text-lg font-bold text-gray-900">Ratio Trends</h2>
        <p className="text-xs text-gray-400">
          {ticker.toUpperCase()} &middot; last {windowed.length} annual period{windowed.length === 1 ? "" : "s"}
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {RATIOS.map(spec => {
          const raw = windowed
            .map(p => p[spec.key])
            .filter((v): v is number => typeof v === "number" && !isNaN(v))
          const latest = raw.length > 0 ? raw[raw.length - 1] : null
          const min = raw.length > 0 ? Math.min(...raw) : null
          const max = raw.length > 0 ? Math.max(...raw) : null
          return (
            <div
              key={spec.label}
              className="border border-gray-100 bg-gray-50 rounded-xl p-4"
            >
              <div className="flex items-baseline justify-between mb-2">
                <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
                  {spec.label}
                </p>
                <p className="text-base font-bold font-mono text-gray-900 tabular-nums">
                  {fmt(latest, spec.suffix, spec.decimals)}
                </p>
              </div>
              <Sparkline points={raw} />
              <div className="flex justify-between text-[10px] text-gray-400 mt-1 font-mono">
                <span>min {fmt(min, spec.suffix, spec.decimals)}</span>
                <span>max {fmt(max, spec.suffix, spec.decimals)}</span>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
