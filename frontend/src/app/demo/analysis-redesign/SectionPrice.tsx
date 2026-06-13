"use client"

// Price & technicals — a NEW retail-first section that sits directly under
// the Decision Box, above §1. It is the chart retail opens a stock page for:
// a smoothed price curve with the "room to fair value" zone shaded above it
// (the margin of safety, drawn), a timeframe toggle, 50/200-day moving
// averages, daily volume, and a hover tooltip.
//
// Mock series are deterministic (Math.sin only — no Math.random) so the
// server and client render identically. In the real build this binds to the
// live price/FV history endpoints; the shape and interaction stay the same.
import { useMemo, useState } from "react"
import { ArrowUpRight } from "lucide-react"

import { FAIR_VALUE, PRICE } from "./data"
import { inr, seg, useStageClock } from "./hooks"
import { DEMO_COLORS, TOKENS } from "./theme"
import { Legend, Muted, Ribbon, Section, Swatch } from "./ui"

const TFS = ["1M", "6M", "1Y", "5Y", "Max"] as const
type TF = (typeof TFS)[number]

const CFG: Record<TF, { n: number; start: number; amp: number; w: number; lab: string }> = {
  "1M": { n: 42, start: 1650, amp: 13, w: 2.3, lab: "past month" },
  "6M": { n: 62, start: 1562, amp: 22, w: 2.1, lab: "past 6 months" },
  "1Y": { n: 88, start: 1499, amp: 30, w: 1.8, lab: "past year" },
  "5Y": { n: 116, start: 946, amp: 44, w: 1.5, lab: "past 5 years" },
  Max: { n: 150, start: 255, amp: 28, w: 1.1, lab: "since listing" },
}

const X0 = 56
const X1 = 500
const Y_TOP = 22
const Y_BOT = 172
const VOL_BASE = 210

/** Deterministic price path for a timeframe — trend + a sine wiggle. */
function series(tf: TF): number[] {
  const c = CFG[tf]
  const a: number[] = []
  for (let i = 0; i < c.n; i++) {
    const t = i / (c.n - 1)
    const base = c.start + (PRICE - c.start) * t
    const wig = Math.sin(i * c.w) * c.amp * (0.55 + 0.45 * Math.sin(i * 0.7))
    a.push(Math.max(40, base + (i === c.n - 1 ? 0 : wig)))
  }
  a[c.n - 1] = PRICE
  return a
}

function sma(a: number[], k: number): number[] {
  const o: number[] = []
  for (let i = 0; i < a.length; i++) {
    let sum = 0
    let cnt = 0
    for (let j = Math.max(0, i - k + 1); j <= i; j++) {
      sum += a[j]
      cnt++
    }
    o.push(sum / cnt)
  }
  return o
}

/** Catmull-Rom → bezier, for an elegant curve instead of a jagged polyline. */
function smoothPath(P: [number, number][]): string {
  if (P.length < 2) return ""
  let d = `M${P[0][0].toFixed(1)},${P[0][1].toFixed(1)}`
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[i - 1] ?? P[i]
    const p1 = P[i]
    const p2 = P[i + 1]
    const p3 = P[i + 2] ?? p2
    const c1x = p1[0] + (p2[0] - p0[0]) / 6
    const c1y = p1[1] + (p2[1] - p0[1]) / 6
    const c2x = p2[0] - (p3[0] - p1[0]) / 6
    const c2y = p2[1] - (p3[1] - p1[1]) / 6
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`
  }
  return d
}

export default function SectionPrice() {
  const { ref, elapsed } = useStageClock(900, 0.2)
  const [tf, setTf] = useState<TF>("1Y")
  const [hover, setHover] = useState<number | null>(null)

  const g = useMemo(() => {
    const s = series(tf)
    const n = s.length
    const dMin = Math.min(...s)
    const dMax = Math.max(...s)
    const top = Math.max(dMax, FAIR_VALUE)
    const pad = (top - dMin) * 0.1 || 10
    const lo = dMin - pad
    const hi = top + pad
    const X = (i: number) => X0 + (i / (n - 1)) * (X1 - X0)
    const Y = (p: number) => Y_BOT - ((p - lo) / (hi - lo)) * (Y_BOT - Y_TOP)
    const P: [number, number][] = s.map((p, i) => [X(i), Y(p)])
    // Thin jagged line (real daily volatility) per the locked §7.4 history
    // style — straight segments between dense points, not a smooth curve.
    const sp = "M" + P.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L")
    const fvY = Math.max(Y_TOP + 2, Y(FAIR_VALUE))
    const grid = [0, 1, 2, 3].map((k) => {
      const gy = Y_TOP + 8 + k * ((Y_BOT - Y_TOP - 8) / 3)
      const pr = lo + ((Y_BOT - gy) / (Y_BOT - Y_TOP)) * (hi - lo)
      return { gy, label: inr(pr) }
    })
    const vol = s.map((p, i) => {
      const delta = i ? Math.abs(s[i] - s[i - 1]) : 4
      const h = Math.min(24, 5 + delta * 0.45)
      return { x: X(i) - 2.5, y: VOL_BASE - h, h }
    })
    const ret = ((s[n - 1] - s[0]) / s[0]) * 100
    return {
      s,
      n,
      P,
      sp,
      fvY,
      grid,
      vol,
      ret,
      areaPath: `${sp} L${X1.toFixed(1)},${Y_BOT} L${X0},${Y_BOT} Z`,
      upPath: `${sp} L${X1.toFixed(1)},${fvY.toFixed(1)} L${X0},${fvY.toFixed(1)} Z`,
      d50: smoothPath(sma(s, Math.max(2, Math.round(n / 6))).map((p, i) => [X(i), Y(p)] as [number, number])),
      d200: smoothPath(sma(s, Math.max(3, Math.round(n / 3))).map((p, i) => [X(i), Y(p)] as [number, number])),
      last: P[n - 1],
    }
  }, [tf])

  const clipW = (X1 - X0 + 8) * seg(elapsed, 0, 760)
  const upsidePct = (((FAIR_VALUE - PRICE) / PRICE) * 100).toFixed(0)
  const hv = hover != null ? { x: g.P[hover][0], y: g.P[hover][1], price: g.s[hover] } : null

  return (
    <Section
      id="sec-price"
      title={"Price & technicals"}
      innerRef={ref}
      ribbon={
        <Ribbon tone="info">
          <span
            className="demo-live-pulse inline-block h-1.5 w-1.5 rounded-full"
            style={{ background: DEMO_COLORS.teal }}
            aria-hidden="true"
          />
          Live · NSE
        </Ribbon>
      }
    >
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="num text-[22px] font-medium text-ink">{inr(PRICE)}</span>
          <span
            className="text-[12.5px]"
            style={{ color: g.ret >= 0 ? TOKENS.success : DEMO_COLORS.coralDark }}
          >
            {tf} {g.ret >= 0 ? "+" : ""}
            {g.ret.toFixed(1)}%
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-tone-good-bg px-2.5 py-[3px] text-[11.5px] font-medium text-tone-good-fg">
            <ArrowUpRight size={13} aria-hidden="true" />
            <span className="num">{inr(FAIR_VALUE - PRICE)}</span> to fair value · +{upsidePct}%
          </span>
          <div className="inline-flex overflow-hidden rounded-full border border-border text-[11.5px]">
            {TFS.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTf(t)}
                aria-pressed={tf === t}
                className={`px-3 py-1 transition-colors ${
                  tf === t ? "bg-tone-info-bg font-medium text-tone-info-fg" : "text-caption hover:bg-raised"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      <svg
        viewBox="0 0 560 224"
        width="100%"
        className="block"
        role="img"
        aria-label="HDFC Bank price curve sitting below its fair-value reference, with 50 and 200 day moving averages, daily volume, and the room-to-fair-value zone shaded above the price."
      >
        <defs>
          <linearGradient id="pcArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={DEMO_COLORS.blue} stopOpacity={0.1} />
            <stop offset="1" stopColor={DEMO_COLORS.blue} stopOpacity={0} />
          </linearGradient>
          <linearGradient id="pcUp" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={DEMO_COLORS.teal} stopOpacity={0.08} />
            <stop offset="1" stopColor={DEMO_COLORS.teal} stopOpacity={0.015} />
          </linearGradient>
          <linearGradient id="pcStroke" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor={DEMO_COLORS.blueDark} />
            <stop offset="1" stopColor={DEMO_COLORS.blue} />
          </linearGradient>
          <clipPath id="pcReveal">
            <rect x={X0} y={0} width={clipW.toFixed(1)} height={224} />
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

        <g clipPath="url(#pcReveal)">
          <path d={g.upPath} fill="url(#pcUp)" />
          <path d={g.areaPath} fill="url(#pcArea)" />
          <path d={g.d200} fill="none" stroke={DEMO_COLORS.purple} strokeWidth={1.2} opacity={0.55} strokeLinejoin="round" />
          <path d={g.d50} fill="none" stroke={DEMO_COLORS.amber} strokeWidth={1.2} opacity={0.7} strokeLinejoin="round" />
          <path d={g.sp} fill="none" stroke={DEMO_COLORS.blueDark} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
          <circle cx={g.last[0]} cy={g.last[1]} r={6} fill={DEMO_COLORS.blueDark} opacity={0.12} />
          <circle cx={g.last[0]} cy={g.last[1]} r={3} fill={DEMO_COLORS.blueDark} stroke={TOKENS.surface} strokeWidth={1.5} />
        </g>

        <line x1={X0} x2={X1} y1={g.fvY} y2={g.fvY} stroke={DEMO_COLORS.teal} strokeWidth={1.5} strokeDasharray="5 4" />
        <text x={X1 + 5} y={g.fvY - 3} fontSize={10.5} fontWeight={500} fill={DEMO_COLORS.tealDark} className="num">
          FV {inr(FAIR_VALUE)}
        </text>

        {g.vol.map((v, i) => (
          <rect key={i} x={v.x} y={v.y} width={5} height={v.h} rx={1} fill={DEMO_COLORS.blueLight} opacity={0.7} />
        ))}

        {hv && (
          <g>
            <line x1={hv.x} x2={hv.x} y1={Y_TOP - 4} y2={Y_BOT + 4} stroke={TOKENS.caption} strokeWidth={1} strokeDasharray="3 3" />
            <circle cx={hv.x} cy={hv.y} r={4} fill={TOKENS.surface} stroke={DEMO_COLORS.blueDark} strokeWidth={2.5} />
            {(() => {
              const tx = Math.min(X1 - 84, Math.max(X0, hv.x - 42))
              const ty = Math.max(2, hv.y - 46)
              return (
                <g>
                  <rect x={tx} y={ty} width={84} height={36} rx={6} fill={TOKENS.surface} stroke={TOKENS.border} strokeWidth={0.5} />
                  <text x={tx + 9} y={ty + 16} fontSize={12.5} fontWeight={500} fill={TOKENS.ink} className="num">
                    {inr(hv.price)}
                  </text>
                  <text x={tx + 9} y={ty + 28} fontSize={9.5} fill={TOKENS.caption}>
                    {CFG[tf].lab}
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
            const f = (e.clientX - r.left) / r.width
            let i = Math.round(f * (g.n - 1))
            if (i < 0) i = 0
            if (i > g.n - 1) i = g.n - 1
            setHover(i)
          }}
          onMouseLeave={() => setHover(null)}
        />
      </svg>

      <Legend>
        <span className="inline-flex items-center gap-1.5">
          <Swatch color={DEMO_COLORS.blueDark} /> Price
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block w-3.5 align-middle" style={{ borderTop: `1.5px dashed ${DEMO_COLORS.teal}` }} aria-hidden="true" /> Fair value
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Swatch color={DEMO_COLORS.amber} /> 50 DMA
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Swatch color={DEMO_COLORS.purple} /> 200 DMA
        </span>
        <span className="ml-auto inline-flex items-center gap-1.5">
          <span className="inline-block h-[9px] w-[9px] rounded-[2px]" style={{ background: DEMO_COLORS.teal, opacity: 0.2 }} aria-hidden="true" /> room to fair value
        </span>
      </Legend>

      <Muted className="mt-2 text-[11.5px]">
        The shaded band above the price is the room to fair value — the margin of safety, drawn. Moving
        averages and daily volume are shown for context.
      </Muted>
    </Section>
  )
}
