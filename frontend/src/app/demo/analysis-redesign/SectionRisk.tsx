"use client"

// J · §6 Risk — likelihood × impact matrix with tinted watch zone (dots
// pop with back-ease), worry-index count-up and bullet legend.
import { CircleDashed } from "lucide-react"

import { RISK_DOTS, WORRY_INDEX, WORRY_LEGEND } from "./data"
import { backOut, seg, useStageClock } from "./hooks"
import { DEMO_COLORS, TOKENS } from "./theme"
import { Muted, Ribbon, Section, Subh, TwoCol } from "./ui"

export default function SectionRisk() {
  const { ref, elapsed } = useStageClock(1400, 0.2)
  const worry = Math.round(WORRY_INDEX * seg(elapsed, 0, 1100))

  return (
    <Section
      id="sec-6"
      num="6"
      title="Risk — what could break the thesis"
      innerRef={ref}
      ribbon={
        <Ribbon tone="warn" icon={<CircleDashed size={13} aria-hidden="true" />}>
          Mixed
        </Ribbon>
      }
    >
      <TwoCol align="start">
        <div>
          <Subh>Risk map — likelihood × impact</Subh>
          <svg
            viewBox="0 0 350 235"
            width="100%"
            style={{ maxWidth: 380 }}
            className="block"
            role="img"
            aria-label="Risk matrix plotting likelihood against impact; credit-deposit ratio sits highest."
          >
            <rect x={185} y={20} width={135} height={85} rx={4} fill="rgba(216,90,48,0.08)" />
            <rect x={50} y={105} width={135} height={85} rx={4} fill="rgba(29,158,117,0.07)" />
            <line x1={50} y1={190} x2={320} y2={190} stroke={TOKENS.border} />
            <line x1={50} y1={20} x2={50} y2={190} stroke={TOKENS.border} />
            <text x={185} y={212} textAnchor="middle" fontSize={10} fill={TOKENS.caption}>
              likelihood →
            </text>
            <text x={34} y={105} textAnchor="middle" fontSize={10} fill={TOKENS.caption} transform="rotate(-90 34 105)">
              impact →
            </text>
            <text x={312} y={34} textAnchor="end" fontSize={9.5} fill={DEMO_COLORS.coralDark}>
              watch zone
            </text>
            {RISK_DOTS.map((d, i) => {
              const r = d.r * seg(elapsed, 200 + i * 130, 450, backOut)
              return (
                <g key={d.label}>
                  <circle cx={d.x} cy={d.y} r={Math.max(0, r).toFixed(1)} fill={d.c} opacity={0.85}>
                    <title>{d.label}</title>
                  </circle>
                  <text x={d.x} y={d.y - 12} textAnchor="middle" fontSize={9.5} fill={TOKENS.caption}>
                    {d.label}
                  </text>
                </g>
              )
            })}
          </svg>
        </div>
        <div>
          <div className="mb-2 flex items-baseline gap-2">
            <span className="num text-[24px] font-medium text-warning">{worry}</span>
            <Muted>worry index · low-moderate</Muted>
          </div>
          <div className="text-[12.5px] leading-[1.9] text-caption">
            {WORRY_LEGEND.map((w) => (
              <div key={w.text}>
                <span
                  className="mr-1.5 inline-block h-2 w-2 rounded-full"
                  style={{ background: w.c }}
                  aria-hidden="true"
                />
                {w.text}
              </div>
            ))}
          </div>
        </div>
      </TwoCol>
    </Section>
  )
}
