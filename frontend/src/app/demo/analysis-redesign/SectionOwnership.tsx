"use client"

// K · §7 Ownership & voice (01 waffle + 04 full depth) — waffle grid
// fills cell-by-cell, FII/DII 8-quarter streamgraph clip-reveals,
// insider 3-lane swimlane (▲ ▼ ◆ scale-pop; promoter lane prints
// "none — widely held"), MF holder chips, concall quote cards.
import { CircleCheck, Mic, Quote } from "lucide-react"

import {
  CONCALL_QUOTES,
  DII_8Q,
  FII_8Q,
  INSIDER_EVENTS,
  MF_HOLDERS,
  QTR_LABELS,
  WAFFLE,
} from "./data"
import { backOut, seg, useStageClock } from "./hooks"
import { DEMO_COLORS, TOKENS } from "./theme"
import { Legend, Muted, Ribbon, Section, Subh, Swatch, TwoCol } from "./ui"

export default function SectionOwnership() {
  return (
    <Section
      id="sec-7"
      num="7"
      title="Ownership & voice"
      ribbon={
        <Ribbon tone="good" icon={<CircleCheck size={13} aria-hidden="true" />}>
          High confidence
        </Ribbon>
      }
    >
      <TwoCol align="start">
        <div>
          <Subh>Who owns it — each square is 1%</Subh>
          <Waffle />
          <Legend className="mt-2.5">
            <span className="inline-flex items-center gap-1.5">
              <Swatch color={DEMO_COLORS.blue} /> FII {WAFFLE.fii}%
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Swatch color={DEMO_COLORS.teal} /> DII {WAFFLE.dii}%
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Swatch color={DEMO_COLORS.grayLight} /> Public {WAFFLE.public}%
            </span>
          </Legend>
          <Muted className="mt-2.5">
            Held across 41 mutual-fund schemes · FII stake +120bps qoq · zero promoter holding
            (widely held).
          </Muted>
        </div>
        <div>
          <Subh>Who&apos;s buying — 8-quarter flow</Subh>
          <Streamgraph />
          <div className="mt-1.5 flex flex-wrap gap-3 text-[11.5px] text-caption">
            <span>
              <Pdot color={DEMO_COLORS.blue} /> FII{" "}
              <b className="font-medium" style={{ color: DEMO_COLORS.tealDark }}>
                +120bps qoq
              </b>
            </span>
            <span>
              <Pdot color={DEMO_COLORS.teal} /> DII −30bps
            </span>
            <span>
              <Pdot color={DEMO_COLORS.grayLight} /> Public
            </span>
          </div>
        </div>
      </TwoCol>

      <TwoCol align="start" className="mt-4">
        <div>
          <Subh>Insider &amp; big-money activity — 12 months</Subh>
          <Swimlane />
          <Muted className="text-[11px]">▲ purchase · ▼ sale · ◆ block/bulk deal · marker size = value</Muted>
        </div>
        <div>
          <Subh>Held by 41 mutual-fund schemes</Subh>
          <div className="flex flex-wrap gap-2">
            {MF_HOLDERS.map((m) => (
              <span key={m.name} className="inline-flex items-center gap-1.5 rounded-full bg-raised px-3 py-1 text-[11.5px] text-ink">
                {m.name} <b className="num font-medium">{m.pct}</b>
              </span>
            ))}
            <button type="button" className="cursor-pointer rounded-full bg-raised px-3 py-1 text-[11.5px] text-tone-info-fg">
              +37 more
            </button>
          </div>
        </div>
      </TwoCol>

      <Subh className="mt-4">
        Management voice — Q1 FY26 call{" "}
        <span className="font-normal text-caption">· AI summary from transcript</span>
      </Subh>
      <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
        {CONCALL_QUOTES.map((q) => (
          <div key={q.source} className="rounded-lg bg-raised px-3.5 py-3 text-[12.5px] leading-relaxed text-ink">
            {q.icon === "quote" ? (
              <Quote size={15} aria-hidden="true" className="mr-1 inline align-[-2px] text-caption" />
            ) : (
              <Mic size={15} aria-hidden="true" className="mr-1 inline align-[-2px] text-caption" />
            )}
            {q.text}
            <Muted className="mt-1.5 text-[11px]">{q.source}</Muted>
          </div>
        ))}
      </div>
    </Section>
  )
}

function Pdot({ color }: { color: string }) {
  return (
    <span className="mr-1.5 inline-block h-2 w-2 rounded-full align-[-1px]" style={{ background: color }} aria-hidden="true" />
  )
}

// --- waffle: 100 squares fill one-by-one ---------------------------------
function Waffle() {
  const { ref, elapsed } = useStageClock(1000, 0.3)
  const painted = Math.floor(100 * seg(elapsed, 0, 900, (p) => p))
  return (
    <div
      ref={ref}
      className="grid w-fit gap-[3px]"
      style={{ gridTemplateColumns: "repeat(10, 12px)" }}
      role="img"
      aria-label="Ownership waffle: 47 squares FII, 34 DII, 19 public."
    >
      {Array.from({ length: 100 }, (_, i) => {
        const on = i < painted
        const color = i < WAFFLE.fii ? DEMO_COLORS.blue : i < WAFFLE.fii + WAFFLE.dii ? DEMO_COLORS.teal : DEMO_COLORS.grayLight
        return (
          <div
            key={i}
            className="h-3 w-3 rounded-[2.5px]"
            style={{ background: on ? color : "var(--color-raised)" }}
          />
        )
      })}
    </div>
  )
}

// --- FII/DII streamgraph (clip reveal) -----------------------------------
const SW = 360
const sx = (i: number) => 18 + (i / 7) * (SW - 36)
const sy = (v: number) => 12 + ((100 - v) / 100) * 120 * 1.55 - 38

function bandPoints(lo: number[], hi: number[]): string {
  let pts = ""
  for (let i = 0; i < 8; i++) pts += `${sx(i).toFixed(1)},${sy(hi[i]).toFixed(1)} `
  for (let j = 7; j >= 0; j--) pts += `${sx(j).toFixed(1)},${sy(lo[j]).toFixed(1)} `
  return pts.trim()
}

function Streamgraph() {
  const { ref, elapsed } = useStageClock(1300, 0.3)
  const clipW = SW * seg(elapsed, 0, 1200)
  const zero = FII_8Q.map(() => 0)
  const fiiDii = FII_8Q.map((v, i) => v + DII_8Q[i])
  const hundred = FII_8Q.map(() => 100)

  return (
    <div ref={ref}>
      <svg
        viewBox="0 0 360 170"
        width="100%"
        className="block"
        role="img"
        aria-label="Stacked ownership flow over eight quarters: FII slid from 49.2 to 45.8 percent then recovered to 47; DII rose steadily to 34 percent."
      >
        <defs>
          <clipPath id="demoStreamClip">
            <rect x={0} y={0} width={clipW.toFixed(1)} height={170} />
          </clipPath>
        </defs>
        <g clipPath="url(#demoStreamClip)">
          <polygon points={bandPoints(zero, FII_8Q)} fill={DEMO_COLORS.blue} fillOpacity={0.45} />
          <polygon points={bandPoints(FII_8Q, fiiDii)} fill={DEMO_COLORS.teal} fillOpacity={0.4} />
          <polygon points={bandPoints(fiiDii, hundred)} fill={DEMO_COLORS.grayLight} fillOpacity={0.3} />
        </g>
        {QTR_LABELS.map((q, i) =>
          i % 2 === 0 ? (
            <text key={q} x={sx(i)} y={164} textAnchor="middle" fontSize={9} fill={TOKENS.caption}>
              {q}
            </text>
          ) : null,
        )}
        <text x={sx(7) - 4} y={sy(FII_8Q[7] / 2) + 4} textAnchor="end" fontSize={10.5} fontWeight={500} fill={DEMO_COLORS.blueDeep} className="num">
          FII 47.0
        </text>
        <text x={sx(7) - 4} y={sy(FII_8Q[7] + DII_8Q[7] / 2) + 4} textAnchor="end" fontSize={10.5} fontWeight={500} fill={DEMO_COLORS.tealDeep} className="num">
          DII 34.0
        </text>
      </svg>
    </div>
  )
}

// --- insider swimlane ------------------------------------------------------
const LANES: [string, number][] = [
  ["Promoter", 36],
  ["Directors & KMP", 72],
  ["Bulk / block", 108],
]

function Swimlane() {
  const { ref, elapsed } = useStageClock(1200, 0.3)
  return (
    <div ref={ref}>
      <svg
        viewBox="0 0 360 150"
        width="100%"
        className="block"
        role="img"
        aria-label="Swimlane timeline: no promoter activity since the company is widely held; director purchases in November and March, one sale in August; a 450 crore block deal in January."
      >
        {LANES.map(([name, y]) => (
          <g key={name}>
            <line x1={110} x2={350} y1={y} y2={y} stroke={TOKENS.border} />
            <text x={104} y={y + 3.5} textAnchor="end" fontSize={10} fill={TOKENS.caption}>
              {name}
            </text>
          </g>
        ))}
        <text x={230} y={30} textAnchor="middle" fontSize={9.5} fill={TOKENS.caption}>
          none — zero promoter holding (widely held)
        </text>
        {["Jul 25", "Oct 25", "Jan 26", "Apr 26"].map((m, i) => (
          <text key={m} x={122 + i * 70} y={140} fontSize={9} fill={TOKENS.caption}>
            {m}
          </text>
        ))}
        {INSIDER_EVENTS.map((e, i) => {
          const scale = seg(elapsed, 200 + i * 130, 450, backOut)
          return (
            <g key={e.tip} transform={`translate(${e.x},${e.laneY}) scale(${Math.max(0, scale).toFixed(2)})`}>
              {e.kind === "block" ? (
                <rect
                  x={-e.size * 0.7}
                  y={-e.size * 0.7}
                  width={e.size * 1.4}
                  height={e.size * 1.4}
                  transform="rotate(45)"
                  fill={DEMO_COLORS.gray}
                  opacity={0.9}
                />
              ) : (
                <polygon
                  points={
                    e.kind === "purchase"
                      ? `0,${-e.size} ${e.size},${e.size} ${-e.size},${e.size}`
                      : `0,${e.size} ${e.size},${-e.size} ${-e.size},${-e.size}`
                  }
                  fill={e.kind === "purchase" ? DEMO_COLORS.teal : DEMO_COLORS.coral}
                  opacity={0.9}
                />
              )}
              <title>{e.tip}</title>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
