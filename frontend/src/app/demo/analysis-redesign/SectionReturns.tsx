"use client"

// What if you'd invested — a retail-magnet "growth of your money" section.
// Pick an amount, one-time vs monthly, and a horizon; the chart grows the
// money along the share price and plots the Nifty 50 on the same axis so the
// comparison is honest (this stock trailed the index over 1–5y and led it at
// 10y). Per the §7.4 locked style: thin jagged value lines + an airy gain
// fill, clip-revealed on enter.
//
// Deterministic (Math.sin only) so server + client render identically. In the
// real build the per-horizon CAGRs bind to adj-close history; the shape and
// interaction stay the same.
import { useMemo, useState } from "react"
import { TrendingUp } from "lucide-react"

import { inr, seg, useStageClock } from "./hooks"
import { DEMO_COLORS, TOKENS } from "./theme"
import { Kpi, Legend, Muted, Ribbon, Section, Swatch } from "./ui"

const HZ = ["1Y", "3Y", "5Y", "10Y"] as const
type Hz = (typeof HZ)[number]
const YEARS: Record<Hz, number> = { "1Y": 1, "3Y": 3, "5Y": 5, "10Y": 10 }

// Annualised PRICE CAGR (dividends excluded). Honest illustrative shape: the
// stock trailed the index over 1–5y, then led it at 10y.
const CAGR = {
  stock: { "1Y": 0.06, "3Y": 0.09, "5Y": 0.12, "10Y": 0.14 },
  nifty: { "1Y": 0.11, "3Y": 0.13, "5Y": 0.15, "10Y": 0.12 },
} as const

const AMOUNTS = [10000, 50000, 100000, 500000]
const AMOUNT_LABELS: Record<number, string> = {
  10000: "₹10K",
  50000: "₹50K",
  100000: "₹1L",
  500000: "₹5L",
}

const X0 = 56
const X1 = 500
const Y_TOP = 20
const Y_BOT = 172

/** Deterministic monthly value-ratio path for a CAGR over `months`, anchored
 *  so the final point hits the exact compounded value (headline stays true). */
function ratios(cagr: number, months: number): number[] {
  const out: number[] = []
  for (let m = 0; m <= months; m++) {
    const base = Math.pow(1 + cagr, m / 12)
    const wig = m === months ? 0 : Math.sin(m * 0.9) * 0.045 * (0.5 + 0.5 * Math.sin(m * 0.35))
    out.push(base * (1 + wig))
  }
  return out
}

export default function SectionReturns() {
  const { ref, elapsed } = useStageClock(900, 0.2)
  const [amount, setAmount] = useState(100000)
  const [sip, setSip] = useState(false)
  const [hz, setHz] = useState<Hz>("5Y")
  const [hover, setHover] = useState<number | null>(null)

  const g = useMemo(() => {
    const months = YEARS[hz] * 12
    const rs = ratios(CAGR.stock[hz], months)
    const rn = ratios(CAGR.nifty[hz], months)
    const n = months + 1

    let vStock: number[]
    let vNifty: number[]
    let invested: number[]
    if (sip) {
      // Equal monthly installments; total deployed across the window = amount.
      const c = amount / n
      vStock = []
      vNifty = []
      invested = []
      for (let m = 0; m < n; m++) {
        let s = 0
        let nf = 0
        for (let k = 0; k <= m; k++) {
          s += c * (rs[m] / rs[k])
          nf += c * (rn[m] / rn[k])
        }
        vStock.push(s)
        vNifty.push(nf)
        invested.push(c * (m + 1))
      }
    } else {
      vStock = rs.map((r) => amount * r)
      vNifty = rn.map((r) => amount * r)
      invested = new Array(n).fill(amount)
    }

    const all = [...vStock, ...vNifty, ...invested]
    const lo = Math.min(...all) * (sip ? 0 : 0.94)
    const hi = Math.max(...all) * 1.05
    const X = (i: number) => X0 + (i / (n - 1)) * (X1 - X0)
    const Y = (v: number) => Y_BOT - ((v - lo) / (hi - lo)) * (Y_BOT - Y_TOP)

    const PS: [number, number][] = vStock.map((v, i) => [X(i), Y(v)])
    const PN: [number, number][] = vNifty.map((v, i) => [X(i), Y(v)])
    const PI: [number, number][] = invested.map((v, i) => [X(i), Y(v)])
    const line = (P: [number, number][]) =>
      "M" + P.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L")
    // Gain band: stock curve forward, then back along the amount-invested line.
    const gainPath =
      line(PS) +
      " L" +
      PI.slice()
        .reverse()
        .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
        .join(" L") +
      " Z"
    const grid = [0, 1, 2, 3].map((k) => {
      const gy = Y_TOP + 6 + k * ((Y_BOT - Y_TOP - 6) / 3)
      const v = lo + ((Y_BOT - gy) / (Y_BOT - Y_TOP)) * (hi - lo)
      return { gy, label: inr(v) }
    })

    const finalStock = vStock[n - 1]
    const finalNifty = vNifty[n - 1]
    const totalIn = invested[n - 1]
    const gain = finalStock - totalIn
    const gainPct = (gain / totalIn) * 100
    return {
      n,
      vStock,
      spStock: line(PS),
      spNifty: line(PN),
      spInvested: line(PI),
      gainPath,
      grid,
      PS,
      finalStock,
      finalNifty,
      totalIn,
      gain,
      gainPct,
      lastStock: PS[n - 1],
      lastNifty: PN[n - 1],
    }
  }, [amount, sip, hz])

  const clipW = (X1 - X0 + 8) * seg(elapsed, 0, 760)
  const hv = hover != null ? { x: g.PS[hover][0], y: g.PS[hover][1], v: g.vStock[hover] } : null
  const beatNifty = g.finalStock >= g.finalNifty
  const niftyDelta = Math.abs(g.finalStock - g.finalNifty)

  return (
    <Section
      id="sec-returns"
      title="What if you'd invested?"
      innerRef={ref}
      ribbon={
        <Ribbon tone="info">
          <TrendingUp size={13} aria-hidden="true" />
          Growth of your money
        </Ribbon>
      }
    >
      {/* controls — amount · mode · horizon */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="inline-flex overflow-hidden rounded-full border border-border text-[12px]">
          {AMOUNTS.map((a) => (
            <button
              key={a}
              type="button"
              onClick={() => setAmount(a)}
              aria-pressed={amount === a}
              className={`px-3 py-1 transition-colors ${
                amount === a ? "bg-tone-info-bg font-medium text-tone-info-fg" : "text-caption hover:bg-raised"
              }`}
            >
              {AMOUNT_LABELS[a]}
            </button>
          ))}
        </div>
        <div className="inline-flex overflow-hidden rounded-full border border-border text-[12px]">
          <button
            type="button"
            onClick={() => setSip(false)}
            aria-pressed={!sip}
            className={`px-3 py-1 transition-colors ${
              !sip ? "bg-tone-info-bg font-medium text-tone-info-fg" : "text-caption hover:bg-raised"
            }`}
          >
            One-time
          </button>
          <button
            type="button"
            onClick={() => setSip(true)}
            aria-pressed={sip}
            className={`px-3 py-1 transition-colors ${
              sip ? "bg-tone-info-bg font-medium text-tone-info-fg" : "text-caption hover:bg-raised"
            }`}
          >
            Monthly
          </button>
        </div>
        <div className="ml-auto inline-flex overflow-hidden rounded-full border border-border text-[11.5px]">
          {HZ.map((h) => (
            <button
              key={h}
              type="button"
              onClick={() => setHz(h)}
              aria-pressed={hz === h}
              className={`px-3 py-1 transition-colors ${
                hz === h ? "bg-tone-info-bg font-medium text-tone-info-fg" : "text-caption hover:bg-raised"
              }`}
            >
              {h}
            </button>
          ))}
        </div>
      </div>

      {/* plain-language headline */}
      <Muted className="mb-2 text-[13px] text-body">
        {AMOUNT_LABELS[amount]} {sip ? "invested every month" : "invested once"} {hz} ago would be worth{" "}
        <span className="num font-medium text-ink">{inr(g.finalStock)}</span> today —{" "}
        <span
          className="num font-medium"
          style={{ color: g.gain >= 0 ? TOKENS.success : DEMO_COLORS.coralDark }}
        >
          {g.gain >= 0 ? "+" : ""}
          {inr(g.gain)}
        </span>{" "}
        on {inr(g.totalIn)} put in.
      </Muted>

      <svg
        viewBox="0 0 560 200"
        width="100%"
        className="block"
        role="img"
        aria-label={`Value of ${AMOUNT_LABELS[amount]} ${
          sip ? "invested monthly" : "invested once"
        } ${hz} ago grown along the share price, with the Nifty 50 plotted on the same axis.`}
      >
        <defs>
          <linearGradient id="rtGain" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={DEMO_COLORS.teal} stopOpacity={0.16} />
            <stop offset="1" stopColor={DEMO_COLORS.teal} stopOpacity={0.02} />
          </linearGradient>
          <clipPath id="rtReveal">
            <rect x={X0} y={0} width={clipW.toFixed(1)} height={200} />
          </clipPath>
        </defs>

        {g.grid.map((gr, i) => (
          <g key={i}>
            <line x1={X0} x2={X1} y1={gr.gy} y2={gr.gy} stroke={TOKENS.border} strokeWidth={0.5} opacity={0.6} />
            <text x={X0 + 3} y={gr.gy - 3} fontSize={9.5} fill={TOKENS.caption} className="num">
              {gr.label}
            </text>
          </g>
        ))}

        <g clipPath="url(#rtReveal)">
          <path d={g.gainPath} fill="url(#rtGain)" />
          <path
            d={g.spInvested}
            fill="none"
            stroke={TOKENS.caption}
            strokeWidth={1}
            strokeDasharray="4 4"
            opacity={0.8}
          />
          <path
            d={g.spNifty}
            fill="none"
            stroke={DEMO_COLORS.gray}
            strokeWidth={1.3}
            opacity={0.85}
            strokeLinejoin="round"
          />
          <path
            d={g.spStock}
            fill="none"
            stroke={DEMO_COLORS.blueDark}
            strokeWidth={1.6}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          <circle cx={g.lastStock[0]} cy={g.lastStock[1]} r={3} fill={DEMO_COLORS.blueDark} stroke={TOKENS.surface} strokeWidth={1.5} />
          <circle cx={g.lastNifty[0]} cy={g.lastNifty[1]} r={2.4} fill={DEMO_COLORS.gray} stroke={TOKENS.surface} strokeWidth={1.3} />
        </g>

        <text x={X1 + 5} y={g.lastStock[1] + 3.5} fontSize={10} fontWeight={500} fill={DEMO_COLORS.blueDark} className="num">
          {inr(g.finalStock)}
        </text>
        <text x={X1 + 5} y={g.lastNifty[1] + 3.5} fontSize={9.5} fill={DEMO_COLORS.gray} className="num">
          {inr(g.finalNifty)}
        </text>

        {hv && (
          <g>
            <line x1={hv.x} x2={hv.x} y1={Y_TOP - 4} y2={Y_BOT + 4} stroke={TOKENS.caption} strokeWidth={1} strokeDasharray="3 3" />
            <circle cx={hv.x} cy={hv.y} r={4} fill={TOKENS.surface} stroke={DEMO_COLORS.blueDark} strokeWidth={2.5} />
            {(() => {
              const tx = Math.min(X1 - 78, Math.max(X0, hv.x - 39))
              const ty = Math.max(2, hv.y - 30)
              return (
                <g>
                  <rect x={tx} y={ty} width={78} height={22} rx={6} fill={TOKENS.surface} stroke={TOKENS.border} strokeWidth={0.5} />
                  <text x={tx + 8} y={ty + 15} fontSize={12} fontWeight={500} fill={TOKENS.ink} className="num">
                    {inr(hv.v)}
                  </text>
                </g>
              )
            })()}
          </g>
        )}

        <rect
          x={X0}
          y={Y_TOP - 4}
          width={X1 - X0}
          height={Y_BOT - Y_TOP + 8}
          fill="transparent"
          style={{ cursor: "crosshair" }}
          onMouseMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect()
            let i = Math.round(((e.clientX - r.left) / r.width) * (g.n - 1))
            if (i < 0) i = 0
            if (i > g.n - 1) i = g.n - 1
            setHover(i)
          }}
          onMouseLeave={() => setHover(null)}
        />
      </svg>

      <Legend>
        <span className="inline-flex items-center gap-1.5">
          <Swatch color={DEMO_COLORS.blueDark} /> Your investment
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Swatch color={DEMO_COLORS.gray} /> Nifty 50
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block w-3.5 align-middle" style={{ borderTop: `1px dashed ${TOKENS.caption}` }} aria-hidden="true" /> Amount invested
        </span>
        <span className="ml-auto inline-flex items-center gap-1.5">
          <span className="inline-block h-[9px] w-[9px] rounded-[2px]" style={{ background: DEMO_COLORS.teal, opacity: 0.2 }} aria-hidden="true" /> gain
        </span>
      </Legend>

      <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <Kpi label="Worth today" value={inr(g.finalStock)} />
        <Kpi label="You put in" value={inr(g.totalIn)} />
        <Kpi
          label="Total gain"
          value={`${g.gain >= 0 ? "+" : ""}${inr(g.gain)}`}
          sub={`${g.gainPct >= 0 ? "+" : ""}${g.gainPct.toFixed(0)}%`}
          valueClass={g.gain >= 0 ? "text-success" : "text-warning"}
        />
        <Kpi
          label="vs Nifty 50"
          value={`${beatNifty ? "+" : "−"}${inr(niftyDelta)}`}
          sub={beatNifty ? "ahead" : "behind"}
          valueClass={beatNifty ? "text-success" : "text-warning"}
        />
      </div>

      <Muted className="mt-2.5 text-[11.5px]">
        Based on past share-price movement; dividends excluded. The Nifty 50 line is the same money in the
        index over the same window. Past performance is not a guide to the future — illustrative, not advice.
      </Muted>
    </Section>
  )
}
