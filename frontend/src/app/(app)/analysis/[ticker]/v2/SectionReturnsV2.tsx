"use client"

/**
 * SectionReturnsV2 (#sec-returns) — "What if you'd invested?", on REAL
 * data.
 *
 * PORTED visuals from app/demo/analysis-redesign/SectionReturns.tsx:
 * amount + horizon pickers, the plain-language headline, the jagged
 * growth-of-money curve with an airy gain fill (§7.4 — real daily
 * volatility, NO Catmull-Rom smoothing), a hover scrubber, and the
 * stat tiles.
 *
 * Real data wiring (DEFERRED — gated by IntersectionObserver via
 * useInViewOnce so the query fires only when scrolled to, NOT on mount):
 *   - getTotalReturn(ticker, years, initialInvestment)
 *       → TotalReturnResponse {
 *           curve[]{date, price_return, total_return},  // cumulative %
 *           initial_investment, total_return_value, price_only_value,
 *           price_return, total_return, dividend_boost_pct, ...
 *         }
 *   The amount picker drives `initial_investment`; the horizon picker
 *   drives `years`. Each combination is its own cache key.
 *
 * BACKEND GAPS — surfaced honestly, never fabricated:
 *   - SIP (monthly / systematic) mode is NOT in the endpoint, so the
 *     one-time / monthly toggle is OMITTED entirely (only lump-sum is
 *     real). No "coming soon" stub control is shown.
 *   - A Nifty-50 benchmark line is NOT in the response, so the
 *     comparison line + "vs Nifty 50" tile are OMITTED. A footnote
 *     names this as a backend gap rather than drawing a fake index.
 *
 * The endpoint gives a price-only path AND a dividend-reinvested
 * (total-return) path. We plot the total-return money curve as the
 * headline and the price-only path as the faint reference, both REAL.
 *
 * SEBI: "Past performance is not a guide to the future — illustrative,
 * not advice." All numbers below are backend-computed; static labels
 * are descriptive only.
 */

import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { TrendingUp } from "lucide-react"

import { getTotalReturn, type TotalReturnResponse } from "@/lib/api"
import { useInViewOnce } from "@/components/anim"
import { formatCurrency } from "@/lib/utils"
import { formatPct } from "@/lib/formatNumbers"

import { DEMO_COLORS, TOKENS } from "@/app/demo/analysis-redesign/theme"
import { Kpi, Legend, Muted, Ribbon, Section, Subh, Swatch } from "@/app/demo/analysis-redesign/ui"

const HORIZONS = [1, 3, 5, 10] as const
type Horizon = (typeof HORIZONS)[number]

const AMOUNTS = [10_000, 50_000, 100_000, 500_000] as const
const AMOUNT_LABELS: Record<number, string> = {
  10_000: "₹10K",
  50_000: "₹50K",
  100_000: "₹1L",
  500_000: "₹5L",
}

// SVG plot box.
const X0 = 56
const X1 = 500
const Y_TOP = 20
const Y_BOT = 172

export default function SectionReturnsV2({ ticker }: { ticker: string }) {
  const { ref, inView } = useInViewOnce<HTMLElement>(0)
  const [amount, setAmount] = useState<number>(100_000)
  const [horizon, setHorizon] = useState<Horizon>(5)
  const [hover, setHover] = useState<number | null>(null)

  // DEFERRED — fires only once in view; re-fires per (amount, horizon).
  const trQ = useQuery({
    queryKey: ["v2-total-return", ticker, horizon, amount],
    queryFn: () => getTotalReturn(ticker, horizon, amount),
    enabled: !!ticker && inView,
    staleTime: 5 * 60_000,
  })

  const resp = trQ.data ?? null

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
      {/* controls — amount · horizon (NO SIP toggle: not in the endpoint) */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Picker
          options={AMOUNTS.map((a) => [a, AMOUNT_LABELS[a]] as const)}
          value={amount}
          onChange={setAmount}
          ariaLabel="Amount invested"
        />
        <Picker
          options={HORIZONS.map((h) => [h, `${h}Y`] as const)}
          value={horizon}
          onChange={(v) => setHorizon(v as Horizon)}
          ariaLabel="Horizon"
          className="ml-auto"
        />
      </div>

      {trQ.isLoading ? (
        <SkeletonBlock height={230} label="Loading return history" />
      ) : resp && (resp.curve?.length ?? 0) >= 2 && resp.total_return_value != null ? (
        <ReturnsChart
          ticker={ticker}
          amountLabel={AMOUNT_LABELS[amount] ?? formatCurrency(amount, undefined, ticker)}
          horizon={horizon}
          resp={resp}
          hover={hover}
          onHover={setHover}
        />
      ) : (
        <Muted className="py-4">
          {resp?.data_source === "unavailable" || (resp && (resp.curve?.length ?? 0) < 2)
            ? `Not enough price history to grow ${AMOUNT_LABELS[amount] ?? "this amount"} over ${horizon} year${horizon > 1 ? "s" : ""} yet.`
            : "Return history is unavailable for this company right now."}
        </Muted>
      )}

      <Muted className="mt-2.5 text-[11.5px]">
        Based on past share-price movement; the headline line reinvests dividends, the faint line is
        price only. A Nifty-50 comparison line is not yet wired on this surface. Past performance is
        not a guide to the future — illustrative, not advice.
      </Muted>
    </Section>
  )
}

/* ================================================================== */
/*  Growth-of-money chart (jagged total-return curve + gain fill)     */
/* ================================================================== */

function ReturnsChart({
  ticker,
  amountLabel,
  horizon,
  resp,
  hover,
  onHover,
}: {
  ticker: string
  amountLabel: string
  horizon: Horizon
  resp: TotalReturnResponse
  hover: number | null
  onHover: (i: number | null) => void
}) {
  const invested = resp.initial_investment
  const curve = resp.curve

  const g = useMemo(() => {
    const n = curve.length
    // Money value at each date = invested × (1 + cumulative-return/100).
    const vTotal = curve.map((c) => invested * (1 + c.total_return / 100))
    const vPrice = curve.map((c) => invested * (1 + c.price_return / 100))

    const all = [...vTotal, ...vPrice, invested]
    const lo = Math.min(...all) * 0.96
    const hi = Math.max(...all) * 1.04
    const span = hi - lo || 1

    const X = (i: number) => X0 + (i / (n - 1)) * (X1 - X0)
    const Y = (v: number) => Y_BOT - ((v - lo) / span) * (Y_BOT - Y_TOP)

    const PT: [number, number][] = vTotal.map((v, i) => [X(i), Y(v)])
    const PP: [number, number][] = vPrice.map((v, i) => [X(i), Y(v)])
    const investedY = Y(invested)

    // JAGGED polyline — straight segments through every real point, no
    // curve smoothing (§7.4).
    const line = (P: [number, number][]) => "M" + P.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L")

    // Gain band: total-return curve forward, then back along the
    // invested baseline.
    const gainPath = line(PT) + ` L${X1.toFixed(1)},${investedY.toFixed(1)} L${X0.toFixed(1)},${investedY.toFixed(1)} Z`

    const grid = [0, 1, 2, 3].map((k) => {
      const gy = Y_TOP + 6 + k * ((Y_BOT - Y_TOP - 6) / 3)
      const v = lo + ((Y_BOT - gy) / (Y_BOT - Y_TOP)) * (hi - lo)
      return { gy, v }
    })

    const finalTotal = vTotal[n - 1]
    const finalPrice = vPrice[n - 1]
    const gain = finalTotal - invested
    const gainPct = (gain / invested) * 100
    return {
      n,
      vTotal,
      spTotal: line(PT),
      spPrice: line(PP),
      gainPath,
      grid,
      investedY,
      PT,
      finalTotal,
      finalPrice,
      gain,
      gainPct,
      lastTotal: PT[n - 1],
      lastPrice: PP[n - 1],
    }
  }, [curve, invested])

  const hv = hover != null && hover < g.PT.length ? { x: g.PT[hover][0], y: g.PT[hover][1], v: g.vTotal[hover] } : null
  const fmtMoney = (v: number) => formatCurrency(Math.round(v), undefined, ticker)
  const dividendBoost = resp.dividend_boost_pct

  return (
    <>
      {/* plain-language headline */}
      <Muted className="mb-2 text-[13px] text-body">
        {amountLabel} invested {horizon} year{horizon > 1 ? "s" : ""} ago would be worth{" "}
        <span className="num font-medium text-ink">{fmtMoney(g.finalTotal)}</span> today —{" "}
        <span
          className="num font-medium"
          style={{ color: g.gain >= 0 ? TOKENS.success : DEMO_COLORS.coralDark }}
        >
          {g.gain >= 0 ? "+" : ""}
          {fmtMoney(g.gain)}
        </span>{" "}
        on {fmtMoney(invested)} put in.
      </Muted>

      <svg
        viewBox="0 0 560 200"
        width="100%"
        className="block"
        role="img"
        aria-label={`Value of ${amountLabel} invested ${horizon} years ago grown along the share price, dividends reinvested.`}
      >
        <defs>
          <linearGradient id="v2RtGain" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={DEMO_COLORS.teal} stopOpacity={0.16} />
            <stop offset="1" stopColor={DEMO_COLORS.teal} stopOpacity={0.02} />
          </linearGradient>
        </defs>

        {g.grid.map((gr, i) => (
          <g key={i}>
            <line x1={X0} x2={X1} y1={gr.gy} y2={gr.gy} stroke={TOKENS.border} strokeWidth={0.5} opacity={0.6} />
            <text x={X0 + 3} y={gr.gy - 3} fontSize={9.5} fill={TOKENS.caption} className="num">
              {fmtMoney(gr.v)}
            </text>
          </g>
        ))}

        {/* amount-invested baseline */}
        <line
          x1={X0}
          x2={X1}
          y1={g.investedY}
          y2={g.investedY}
          stroke={TOKENS.caption}
          strokeWidth={1}
          strokeDasharray="4 4"
          opacity={0.8}
        />

        {/* airy gain fill, then the price-only reference, then the jagged
            total-return money line */}
        <path d={g.gainPath} fill="url(#v2RtGain)" />
        <path d={g.spPrice} fill="none" stroke={DEMO_COLORS.gray} strokeWidth={1.3} opacity={0.85} strokeLinejoin="round" />
        <path
          d={g.spTotal}
          fill="none"
          stroke={DEMO_COLORS.blueDark}
          strokeWidth={1.6}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <circle cx={g.lastTotal[0]} cy={g.lastTotal[1]} r={3} fill={DEMO_COLORS.blueDark} stroke={TOKENS.surface} strokeWidth={1.5} />
        <circle cx={g.lastPrice[0]} cy={g.lastPrice[1]} r={2.4} fill={DEMO_COLORS.gray} stroke={TOKENS.surface} strokeWidth={1.3} />

        <text x={X1 + 5} y={g.lastTotal[1] + 3.5} fontSize={10} fontWeight={500} fill={DEMO_COLORS.blueDark} className="num">
          {fmtMoney(g.finalTotal)}
        </text>
        <text x={X1 + 5} y={g.lastPrice[1] + 3.5} fontSize={9.5} fill={DEMO_COLORS.gray} className="num">
          {fmtMoney(g.finalPrice)}
        </text>

        {hv && (
          <g>
            <line x1={hv.x} x2={hv.x} y1={Y_TOP - 4} y2={Y_BOT + 4} stroke={TOKENS.caption} strokeWidth={1} strokeDasharray="3 3" />
            <circle cx={hv.x} cy={hv.y} r={4} fill={TOKENS.surface} stroke={DEMO_COLORS.blueDark} strokeWidth={2.5} />
            {(() => {
              const tx = Math.min(X1 - 84, Math.max(X0, hv.x - 42))
              const ty = Math.max(2, hv.y - 30)
              return (
                <g>
                  <rect x={tx} y={ty} width={84} height={22} rx={6} fill={TOKENS.surface} stroke={TOKENS.border} strokeWidth={0.5} />
                  <text x={tx + 8} y={ty + 15} fontSize={12} fontWeight={500} fill={TOKENS.ink} className="num">
                    {fmtMoney(hv.v)}
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
            onHover(i)
          }}
          onMouseLeave={() => onHover(null)}
        />
      </svg>

      <Legend>
        <span className="inline-flex items-center gap-1.5">
          <Swatch color={DEMO_COLORS.blueDark} /> Your investment (dividends reinvested)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Swatch color={DEMO_COLORS.gray} /> Price only
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block w-3.5 align-middle" style={{ borderTop: `1px dashed ${TOKENS.caption}` }} aria-hidden="true" />{" "}
          Amount invested
        </span>
        <span className="ml-auto inline-flex items-center gap-1.5">
          <span className="inline-block h-[9px] w-[9px] rounded-[2px]" style={{ background: DEMO_COLORS.teal, opacity: 0.2 }} aria-hidden="true" />{" "}
          gain
        </span>
      </Legend>

      <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <Kpi label="Worth today" value={fmtMoney(g.finalTotal)} />
        <Kpi label="You put in" value={fmtMoney(invested)} />
        <Kpi
          label="Total gain"
          value={`${g.gain >= 0 ? "+" : ""}${fmtMoney(g.gain)}`}
          sub={formatPct(g.gainPct, { signed: true, decimals: 0 })}
          valueClass={g.gain >= 0 ? "text-success" : "text-warning"}
        />
        <Kpi
          label="Dividend lift"
          value={dividendBoost != null ? formatPct(dividendBoost, { signed: true }) : "—"}
          sub="vs price only"
        />
      </div>
    </>
  )
}

/* ------------------------------------------------------------------ */
/*  Small UI                                                           */
/* ------------------------------------------------------------------ */

function Picker<T extends number>({
  options,
  value,
  onChange,
  ariaLabel,
  className = "",
}: {
  options: readonly (readonly [T, string])[]
  value: T
  onChange: (v: T) => void
  ariaLabel: string
  className?: string
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={`inline-flex overflow-hidden rounded-full border border-border text-[12px] ${className}`}
    >
      {options.map(([v, label]) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          aria-pressed={value === v}
          className={`px-3 py-1 transition-colors ${
            value === v ? "bg-tone-info-bg font-medium text-tone-info-fg" : "text-caption hover:bg-raised"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

function SkeletonBlock({ height, label }: { height: number; label: string }) {
  return (
    <div
      className="flex animate-pulse items-center justify-center rounded-lg border border-border/50 bg-raised"
      style={{ height }}
      role="status"
      aria-live="polite"
    >
      <span className="text-[12px] text-caption">{label}…</span>
    </div>
  )
}
