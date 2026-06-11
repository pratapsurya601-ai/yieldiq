"use client"

// G · §4 Financials — KPI tiles, 5y NII/profit grouped columns, the TRUE
// waterfall profit bridge (02), balance-sheet/asset-quality tiles, ROE
// lollipops, 10-cell score battery, dividend staircase, collapsible P&L.
// Each visual carries its own viewport clock so it fires on its own reveal.
import { useState } from "react"
import { CircleCheck, Coins, Table } from "lucide-react"

import {
  BRIDGE_CONNECTORS,
  BRIDGE_STEPS,
  DIVIDEND_STEPS,
  FY,
  NII_5Y,
  NP_5Y,
  PNL_ROWS,
  QUALITY_SCORE,
  QUALITY_SECTOR,
  ROE_PEERS,
} from "./data"
import { seg, useStageClock } from "./hooks"
import { DEMO_COLORS, TOKENS } from "./theme"
import { Kpi, Legend, Muted, Ribbon, Section, Subh, Swatch, TwoCol } from "./ui"

export default function SectionFinancials() {
  return (
    <Section
      id="sec-4"
      num="4"
      title="Financials — statements in order"
      ribbon={
        <Ribbon tone="good" icon={<CircleCheck size={13} aria-hidden="true" />}>
          High confidence
        </Ribbon>
      }
    >
      <div className="mb-3.5 grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <Kpi label="Net interest income" value="₹1.21L cr" sub={<span className="text-success">+9%</span>} />
        <Kpi label="Net profit" value="₹66k cr" sub={<span className="text-success">+11%</span>} />
        <Kpi label="Net interest margin" value="3.6%" />
        <Kpi label="Cost / income" value="40%" />
      </div>

      <Subh>Income &amp; earnings — 5-year trend (₹ &apos;000 cr)</Subh>
      <IncomeColumns />
      <Legend>
        <span className="inline-flex items-center gap-1.5">
          <Swatch color={DEMO_COLORS.blue} />
          NII
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Swatch color={DEMO_COLORS.teal} />
          Net profit
        </span>
        <span className="ml-auto text-caption">Profit CAGR — 3y 18% · 5y 16% · 10y 19%</span>
      </Legend>

      <Subh className="mt-4.5">Profit bridge — FY25 (₹ &apos;000 cr)</Subh>
      <ProfitBridge />
      <Muted className="mt-1">
        Every ₹100 of income keeps ₹40 as profit after costs, provisions and tax — a 40%
        cost-income ratio doing its job.
      </Muted>

      <Subh className="mt-4.5">Balance sheet &amp; asset quality</Subh>
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Deposits" value="₹25.6L cr" />
        <Kpi label="Credit-deposit" value="99%" valueClass="text-warning" />
        <Kpi label="CASA" value="38%" />
        <Kpi label="Capital adequacy" value="18.8%" valueClass="text-success" />
        <Kpi label="Gross NPA" value="1.30%" />
        <Kpi label="Provision coverage" value="71%" />
      </div>

      <TwoCol align="start" className="mt-4.5">
        <div>
          <Subh>Return on equity vs peers</Subh>
          <RoeLollipops />
        </div>
        <div>
          <Subh>YieldIQ quality score</Subh>
          <ScoreBattery />
          <Muted className="mt-2.5">
            Business-quality sub-signal — distinct from the valuation verdict above.
          </Muted>
        </div>
      </TwoCol>

      <Subh className="mt-4.5">
        <Coins size={15} aria-hidden="true" className="mr-1 inline align-[-2px]" />
        Dividends &amp; capital allocation
      </Subh>
      <TwoCol>
        <div>
          <Muted className="mb-1">Dividend per share — raised 5 years straight</Muted>
          <DividendStaircase />
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          <Kpi label="Dividend yield" value="1.1%" sub="sector 0.7%" />
          <Kpi label="Payout ratio" value="22%" />
          <Kpi label="Years of growth" value="5" />
          <Kpi label="Earnings cover" value="4.5×" valueClass="text-success" />
        </div>
      </TwoCol>

      <PnlTable />
    </Section>
  )
}

// --- 5y grouped columns -------------------------------------------------
function IncomeColumns() {
  const { ref, elapsed } = useStageClock(1000, 0.3)
  const grow = seg(elapsed, 0, 900)
  return (
    <div ref={ref} className="flex h-[140px] items-end gap-3.5 px-1">
      {FY.map((y, i) => (
        <div key={y} className="flex flex-1 flex-col items-center gap-1">
          <div className="flex h-[115px] items-end gap-1">
            <div
              className="w-[15px] rounded-t-[3px]"
              style={{ background: DEMO_COLORS.blue, height: `${(NII_5Y[i] * 0.9 * grow).toFixed(1)}px` }}
              title={`NII ${y}`}
            />
            <div
              className="w-[15px] rounded-t-[3px]"
              style={{ background: DEMO_COLORS.teal, height: `${(NP_5Y[i] * 0.9 * grow).toFixed(1)}px` }}
              title={`Net profit ${y}`}
            />
          </div>
          <div className="text-[11px] text-caption">{y}</div>
        </div>
      ))}
    </div>
  )
}

// --- TRUE waterfall profit bridge (02) ----------------------------------
const BRIDGE_BASE = 196
const BRIDGE_SCALE = 172 / 166
const wy = (v: number) => BRIDGE_BASE - v * BRIDGE_SCALE
const colX = (i: number) => 36 + i * 86

function ProfitBridge() {
  const { ref, elapsed } = useStageClock(1600, 0.3)
  return (
    <div ref={ref}>
      <svg
        viewBox="0 0 560 240"
        width="100%"
        style={{ maxWidth: 640 }}
        className="block"
        role="img"
        aria-label="Waterfall from net interest income 121 plus other income 45 minus operating expense 66 minus provisions 11 minus tax 23 equals net profit 66 thousand crore rupees."
      >
        {[0, 50, 100, 150].map((v) => (
          <g key={v}>
            <line x1={30} x2={530} y1={wy(v)} y2={wy(v)} stroke={TOKENS.border} strokeDasharray="2 5" />
            <text x={536} y={wy(v) + 3} fontSize={9.5} fill={TOKENS.caption} className="num">
              {v}
            </text>
          </g>
        ))}
        {BRIDGE_STEPS.map((s, i) => {
          const grow = seg(elapsed, i * 170, 550)
          const fullH = (s.hi - s.lo) * BRIDGE_SCALE
          const h = fullH * grow
          const topY = wy(s.hi)
          const y = s.sub ? topY : wy(s.lo) - h
          return (
            <g key={s.n}>
              <rect x={colX(i)} y={y.toFixed(1)} width={58} height={h.toFixed(1)} rx={4} fill={s.c} fillOpacity={s.sub ? 0.8 : 0.9}>
                <title>{s.tip}</title>
              </rect>
              <text
                x={colX(i) + 29}
                y={topY - 7}
                textAnchor="middle"
                fontSize={12}
                fontWeight={500}
                fill={s.sub ? DEMO_COLORS.amberDark : TOKENS.ink}
                opacity={elapsed >= i * 170 + 550 ? 1 : 0}
                style={{ transition: "opacity .4s" }}
                className="num"
              >
                {s.v}
              </text>
              <text x={colX(i) + 29} y={216} textAnchor="middle" fontSize={10} fill={TOKENS.caption}>
                {s.n}
              </text>
            </g>
          )
        })}
        {BRIDGE_CONNECTORS.map(([level, from, to], i) => (
          <line
            key={`${from}-${to}`}
            x1={colX(from) + 58}
            x2={colX(to)}
            y1={wy(level)}
            y2={wy(level)}
            stroke={TOKENS.caption}
            strokeDasharray="3 3"
            opacity={elapsed >= i * 170 + 450 ? 0.6 : 0}
            style={{ transition: "opacity .3s" }}
          />
        ))}
        <line x1={30} x2={530} y1={BRIDGE_BASE} y2={BRIDGE_BASE} stroke={TOKENS.border} />
      </svg>
    </div>
  )
}

// --- ROE lollipops -------------------------------------------------------
const lx = (v: number) => 130 + ((v - 13) / 6) * 400

function RoeLollipops() {
  const { ref, elapsed } = useStageClock(1500, 0.3)
  return (
    <div ref={ref}>
      <svg
        viewBox="0 0 560 180"
        width="100%"
        className="block"
        role="img"
        aria-label="Lollipop chart of return on equity across five banks; HDFC Bank highlighted at 16.1 percent."
      >
        {[14, 16, 18].map((v) => (
          <g key={v}>
            <line x1={lx(v)} x2={lx(v)} y1={16} y2={158} stroke={TOKENS.border} strokeDasharray="2 5" />
            <text x={lx(v)} y={174} textAnchor="middle" fontSize={10} fill={TOKENS.caption} className="num">
              {v}%
            </text>
          </g>
        ))}
        {ROE_PEERS.map((p, i) => {
          const y = 30 + i * 30
          const slide = seg(elapsed, i * 100, 800)
          const x = 130 + (lx(p.roe) - 130) * slide
          const settled = elapsed >= i * 100 + 800
          const color = p.me ? DEMO_COLORS.teal : DEMO_COLORS.gray
          return (
            <g key={p.t}>
              <text
                x={122}
                y={y + 4}
                textAnchor="end"
                fontSize={11}
                fontWeight={p.me ? 500 : 400}
                fill={p.me ? DEMO_COLORS.tealDark : TOKENS.caption}
              >
                {p.t}
              </text>
              <line x1={130} y1={y} x2={x.toFixed(1)} y2={y} stroke={color} strokeWidth={2} />
              <circle cx={x.toFixed(1)} cy={y} r={p.me ? 6 : 4.5} fill={color} />
              <text
                x={(lx(p.roe) + 12).toFixed(1)}
                y={y + 4}
                fontSize={11}
                fontWeight={500}
                fill={TOKENS.ink}
                opacity={settled ? 1 : 0}
                style={{ transition: "opacity .3s" }}
                className="num"
              >
                {p.roe}%
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

// --- 10-cell score battery ----------------------------------------------
function ScoreBattery() {
  const { ref, elapsed } = useStageClock(1300, 0.3)
  const fill = QUALITY_SCORE * seg(elapsed, 0, 1200)
  return (
    <div ref={ref} className="flex items-center gap-3">
      <div className="flex flex-1 gap-1" role="img" aria-label={`Quality score ${QUALITY_SCORE} of 100, sector median ${QUALITY_SECTOR}.`}>
        {Array.from({ length: 10 }, (_, i) => {
          const cellFill = Math.max(0, Math.min(1, fill / 10 - i))
          return (
            <div key={i} className="relative h-[22px] flex-1 overflow-hidden rounded border border-border">
              <i
                className="absolute bottom-0 left-0 top-0 block"
                style={{ width: `${(cellFill * 100).toFixed(1)}%`, background: DEMO_COLORS.teal }}
              />
            </div>
          )
        })}
      </div>
      <div className="text-right">
        <div className="num text-[24px] font-medium text-ink">{Math.round(fill)}</div>
        <div className="text-[11.5px] text-caption">sector {QUALITY_SECTOR}</div>
      </div>
    </div>
  )
}

// --- dividend staircase ---------------------------------------------------
const STAIR_PATH = "M30,83 H95 V53 H160 V42 H225 V40 H290 V32 h20"
const STAIR_LEN = 331 // summed segment lengths of STAIR_PATH

function DividendStaircase() {
  const { ref, elapsed } = useStageClock(1500, 0.3)
  const drawn = seg(elapsed, 0, 1400)
  return (
    <div ref={ref}>
      <svg
        viewBox="0 0 330 130"
        width="100%"
        style={{ maxWidth: 380 }}
        className="block"
        role="img"
        aria-label="Dividend staircase rising from 6.5 rupees in FY21 to 22 rupees in FY25."
      >
        <path
          d={STAIR_PATH}
          fill="none"
          stroke={DEMO_COLORS.teal}
          strokeWidth={2.5}
          strokeLinejoin="round"
          strokeDasharray={STAIR_LEN}
          strokeDashoffset={(STAIR_LEN * (1 - drawn)).toFixed(1)}
        />
        {DIVIDEND_STEPS.map((d) => (
          <g key={d.fy}>
            <text x={d.x} y={122} textAnchor="middle" fontSize={10} fill={TOKENS.caption}>
              {d.fy}
            </text>
            <text x={d.x} y={d.y - 9} textAnchor="middle" fontSize={10.5} fontWeight={500} fill={DEMO_COLORS.tealDark} className="num">
              {d.label}
            </text>
            <circle cx={d.x} cy={d.y} r={3.5} fill={DEMO_COLORS.teal} />
          </g>
        ))}
      </svg>
    </div>
  )
}

// --- collapsible 5y P&L ----------------------------------------------------
function PnlTable() {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-3.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-1.5 text-[12.5px] text-caption transition-colors hover:bg-raised"
      >
        <Table size={13} aria-hidden="true" />
        {open ? "Hide 5-year P&L" : "Show 5-year P&L"}
      </button>
      <div className="overflow-hidden transition-[max-height] duration-300" style={{ maxHeight: open ? 460 : 0 }}>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[430px] border-collapse text-[12px]">
            <thead>
              <tr className="border-b border-border/70 text-caption">
                <th className="px-2 py-1.5 text-left font-medium">₹ &apos;000 cr</th>
                {FY.map((y) => (
                  <th key={y} className="px-2 py-1.5 text-right font-medium">
                    {y}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {PNL_ROWS.map(([name, values, bold]) => (
                <tr key={name} className={`border-t border-border/50 ${bold ? "font-medium" : ""}`}>
                  <td className={`px-2 py-1.5 ${bold ? "text-ink" : "text-caption"}`}>{name}</td>
                  {values.map((v, i) => (
                    <td key={i} className="num px-2 py-1.5 text-right text-ink">
                      {v}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
