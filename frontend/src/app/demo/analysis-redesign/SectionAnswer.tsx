"use client"

// D · §1 The Answer — semicircle gauge (needle swings with overshoot,
// green arc pulses on landing) + vertical price ladder ("Now" marker
// climbs) + tappable confidence chip opening the 5-pillar dot-matrix.
import { useState } from "react"
import { CircleCheck } from "lucide-react"

import { useReducedMotion } from "@/components/anim"

import { CONFIDENCE_PILLARS } from "./data"
import { backOut, seg, useStageClock } from "./hooks"
import { DEMO_COLORS, TOKENS } from "./theme"
import { Muted, Section, Subh, TwoCol } from "./ui"

const NEEDLE_TARGET = 70 // % along the arc → lands in the undervalued zone
const LADDER_RISE = 218 - 158.9 // bottom of rail → ₹1,684

export default function SectionAnswer() {
  const { ref, elapsed } = useStageClock(2000, 0.2)
  const [cfOpen, setCfOpen] = useState(false)

  // Needle with back-ease overshoot
  const needleV = NEEDLE_TARGET * seg(elapsed, 0, 1300, backOut)
  const a = Math.PI - (needleV / 100) * Math.PI
  const nx = 85 + 60 * Math.cos(a)
  const ny = 85 - 60 * Math.sin(a)

  // Green arc pulse on landing (stroke-width 12 → 16 → 12)
  let arcW = 12
  if (elapsed > 1300 && elapsed <= 1470) arcW = 12 + 4 * ((elapsed - 1300) / 170)
  else if (elapsed > 1470 && elapsed <= 1870) arcW = 16 - 4 * ((elapsed - 1470) / 400)
  const landed = elapsed > 1300

  const ladderRise = LADDER_RISE * seg(elapsed, 0, 1300)

  return (
    <Section
      id="sec-1"
      num="1"
      title="The answer — where price sits"
      innerRef={ref}
      ribbon={
        <button
          type="button"
          onClick={() => setCfOpen((v) => !v)}
          aria-expanded={cfOpen}
          className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-tone-good-bg px-2.5 py-[3px] text-[11px] text-tone-good-fg"
        >
          <CircleCheck size={13} aria-hidden="true" />
          High confidence · why?
        </button>
      }
    >
      {/* Confidence depth — 5-pillar dot-matrix (one engine behind every chip) */}
      <div
        className="overflow-hidden transition-[max-height] duration-300 ease-out"
        style={{ maxHeight: cfOpen ? 320 : 0 }}
      >
        <div className="pb-1.5 pt-0.5">
          {CONFIDENCE_PILLARS.map((p, pi) => (
            <div key={p.name} className="flex items-center gap-2.5 py-[5px] text-[12.5px]">
              <span className="w-[150px] shrink-0 text-caption">{p.name}</span>
              <span className="flex shrink-0 gap-[3px]">
                {Array.from({ length: 5 }, (_, di) => (
                  <ConfidenceDot key={di} on={di < p.score} open={cfOpen} order={pi * 5 + di} />
                ))}
              </span>
              <span className="hidden text-[11.5px] text-caption sm:block">{p.why}</span>
            </div>
          ))}
        </div>
        <Muted className="border-t border-border/70 pb-3 pt-2 text-[11.5px]">
          Five pillars, scored 1–5. The same breakdown sits behind every section&apos;s confidence
          chip — one engine, shown where you need it.
        </Muted>
      </div>

      <TwoCol>
        <div className="text-center">
          <Subh>Valuation gauge</Subh>
          <svg
            viewBox="0 0 170 112"
            width="100%"
            style={{ maxWidth: 240 }}
            className="mx-auto block"
            role="img"
            aria-label="Valuation gauge needle settling in the undervalued zone."
          >
            <path d="M15,85 A70,70 0 0 1 63.4,18.4" fill="none" stroke={DEMO_COLORS.coral} strokeWidth={12} strokeLinecap="round" opacity={0.8} />
            <path d="M63.4,18.4 A70,70 0 0 1 106.6,18.4" fill="none" stroke={DEMO_COLORS.amber} strokeWidth={12} />
            <path
              d="M106.6,18.4 A70,70 0 0 1 155,85"
              fill="none"
              stroke={DEMO_COLORS.teal}
              strokeWidth={arcW}
              strokeLinecap="round"
              style={{ transition: "stroke-width .1s" }}
            />
            <line x1={85} y1={85} x2={nx.toFixed(1)} y2={ny.toFixed(1)} stroke={TOKENS.ink} strokeWidth={2.5} strokeLinecap="round" />
            <circle cx={85} cy={85} r={5} fill={TOKENS.ink} />
            <text
              x={85}
              y={106}
              textAnchor="middle"
              fontSize={12}
              fontWeight={500}
              fill={DEMO_COLORS.tealDark}
              opacity={landed ? 1 : 0}
              style={{ transition: "opacity .4s" }}
            >
              16% undervalued
            </text>
          </svg>
          <div className="mx-auto flex max-w-[240px] justify-between px-2 text-[11px] text-caption">
            <span>Overvalued</span>
            <span>Fair</span>
            <span>Undervalued</span>
          </div>
        </div>

        <div className="text-center">
          <Subh>Price ladder</Subh>
          <svg
            viewBox="0 0 240 238"
            width="100%"
            style={{ maxWidth: 250 }}
            className="mx-auto block"
            role="img"
            aria-label="Vertical price ladder from bear 1420 through price 1684 and fair value 2010 to bull 2460."
          >
            <line x1={70} y1={18} x2={70} y2={220} stroke={TOKENS.border} strokeWidth={2} />
            <rect x={64} y={108.8} width={12} height={50.1} rx={3} fill="rgba(29,158,117,0.25)" />
            <line x1={58} y1={39.5} x2={82} y2={39.5} stroke={DEMO_COLORS.tealFaint} strokeWidth={3} />
            <text x={92} y={43} fontSize={11.5} fill={TOKENS.caption} className="num">
              Bull ₹2,460
            </text>
            <line x1={58} y1={108.8} x2={82} y2={108.8} stroke={DEMO_COLORS.teal} strokeWidth={3.5} />
            <text x={92} y={112} fontSize={12} fontWeight={500} fill={DEMO_COLORS.tealDark} className="num">
              Fair ₹2,010
            </text>
            <line x1={58} y1={199.5} x2={82} y2={199.5} stroke={DEMO_COLORS.coralLight} strokeWidth={3} />
            <text x={92} y={203} fontSize={11.5} fill={TOKENS.caption} className="num">
              Bear ₹1,420
            </text>
            <g transform={`translate(0,${(-ladderRise).toFixed(1)})`}>
              <circle cx={70} cy={218} r={6} fill={TOKENS.ink} />
              <text x={58} y={222} fontSize={12} fontWeight={500} fill={TOKENS.ink} textAnchor="end" className="num">
                Now ₹1,684
              </text>
            </g>
          </svg>
          <Muted className="text-[11.5px]">The shaded rung gap is your 16% margin of safety.</Muted>
        </div>
      </TwoCol>

      <Muted className="mt-2">
        5 of 8 estimators agree within ±12%. <JumpLink target="sec-5">Method breakdown →</JumpLink>
      </Muted>
    </Section>
  )
}

function ConfidenceDot({ on, open, order }: { on: boolean; open: boolean; order: number }) {
  const reduced = useReducedMotion()
  const filled = on && open
  return (
    <span
      className="inline-block h-[11px] w-[11px] rounded-full border-[1.5px] transition-colors duration-300"
      style={{
        borderColor: DEMO_COLORS.teal,
        background: filled ? DEMO_COLORS.teal : "transparent",
        transitionDelay: filled && !reduced ? `${order * 45}ms` : "0ms",
      }}
      aria-hidden="true"
    />
  )
}

function JumpLink({ target, children }: { target: string; children: React.ReactNode }) {
  const reduced = useReducedMotion()
  return (
    <button
      type="button"
      className="cursor-pointer text-[12px] text-tone-info-fg hover:underline"
      onClick={() =>
        document.getElementById(target)?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" })
      }
    >
      {children}
    </button>
  )
}
