"use client"

// E · §2 Thesis — tilting balance beam (settles at 58/42 with a springy
// back-ease), impact-weighted tap-to-expand bull/bear points, honesty note.
import { useState } from "react"
import { CircleCheck, CircleDashed, TriangleAlert } from "lucide-react"

import { BEAR_POINTS, BULL_POINTS, type ThesisPoint } from "./data"
import { backOut, seg, useStageClock } from "./hooks"
import { TOKENS } from "./theme"
import { Muted, Ribbon, Section, TwoCol } from "./ui"

export default function SectionThesis() {
  const { ref, elapsed } = useStageClock(1600, 0.2)
  const angle = -6 * seg(elapsed, 0, 1500, backOut)

  return (
    <Section
      id="sec-2"
      num="2"
      title="Thesis — the argument"
      innerRef={ref}
      ribbon={
        <Ribbon tone="warn" icon={<CircleDashed size={13} aria-hidden="true" />}>
          Mixed
        </Ribbon>
      }
    >
      <div className="text-center">
        <svg
          viewBox="0 0 560 132"
          width="100%"
          style={{ maxWidth: 560 }}
          className="mx-auto block"
          role="img"
          aria-label="Balance beam tilting toward the bull side, 58 to 42."
        >
          <g transform={`rotate(${angle.toFixed(2)} 280 62)`}>
            <line x1={130} y1={62} x2={430} y2={62} stroke={TOKENS.caption} strokeWidth={3} strokeLinecap="round" />
            <g>
              <rect x={108} y={26} width={86} height={30} rx={7} fill="var(--color-tone-good-bg)" />
              <text x={151} y={45} textAnchor="middle" fontSize={12.5} fontWeight={500} fill="var(--color-tone-good-fg)">
                Bull 58%
              </text>
              <line x1={151} y1={56} x2={151} y2={62} stroke={TOKENS.caption} strokeWidth={2} />
            </g>
            <g>
              <rect x={366} y={26} width={86} height={30} rx={7} fill="var(--color-tone-warn-bg)" />
              <text x={409} y={45} textAnchor="middle" fontSize={12.5} fontWeight={500} fill="var(--color-tone-warn-fg)">
                Bear 42%
              </text>
              <line x1={409} y1={56} x2={409} y2={62} stroke={TOKENS.caption} strokeWidth={2} />
            </g>
          </g>
          <polygon points="266,96 294,96 280,64" fill={TOKENS.caption} />
          <line x1={180} y1={96} x2={380} y2={96} stroke={TOKENS.border} strokeWidth={1.5} />
          <text x={280} y={122} textAnchor="middle" fontSize={12} fill={TOKENS.caption}>
            Net read — undervalued; deposit growth is the swing factor
          </text>
        </svg>
      </div>

      <Muted className="mb-1 mt-2.5 text-[11.5px]">
        Bars show each point&apos;s impact · tap a point for why it matters
      </Muted>

      <TwoCol align="stretch">
        <div className="rounded-lg bg-raised px-3.5 pb-3 pt-2.5">
          <div className="mb-1 text-[13px] font-medium text-success">Bull case</div>
          <Muted className="mb-1.5">
            A scaling deposit franchise and sector-leading capital compound mid-teens returns — at a
            16% discount to intrinsic value.
          </Muted>
          <PointList points={BULL_POINTS} kind="bull" />
        </div>
        <div className="rounded-lg bg-raised px-3.5 pb-3 pt-2.5">
          <div className="mb-1 text-[13px] font-medium text-warning">Bear case</div>
          <Muted className="mb-1.5">
            A near-100% credit-deposit ratio and post-merger margin dilution cap growth until
            deposits catch up.
          </Muted>
          <PointList points={BEAR_POINTS} kind="bear" />
        </div>
      </TwoCol>

      <div className="mt-3 rounded-lg border border-dashed border-border px-3 py-2.5 text-[12.5px] leading-relaxed text-ink">
        <span className="font-medium">Where we&apos;re honest —</span>{" "}
        <span className="text-caption">
          most confident in the deposit franchise and capital adequacy; least confident in near-term
          margins and terminal growth while merger integration completes.
        </span>
      </div>
    </Section>
  )
}

function PointList({ points, kind }: { points: ThesisPoint[]; kind: "bull" | "bear" }) {
  const [open, setOpen] = useState<number | null>(null)
  const color = kind === "bull" ? TOKENS.success : TOKENS.warning
  const Icon = kind === "bull" ? CircleCheck : TriangleAlert

  return (
    <div>
      {points.map(([headline, impact, detail], i) => (
        <button
          key={headline}
          type="button"
          aria-expanded={open === i}
          onClick={() => setOpen(open === i ? null : i)}
          className="-mx-1.5 block w-[calc(100%+12px)] cursor-pointer rounded-md px-1.5 py-1 text-left transition-colors hover:bg-surface"
        >
          <span className="flex items-start gap-2 text-[12.5px] leading-snug text-ink">
            <Icon size={16} aria-hidden="true" className="mt-px shrink-0" style={{ color }} />
            <span className="flex-1">{headline}</span>
            <span className="ml-2 inline-flex shrink-0 items-center gap-0.5" aria-label={`impact ${impact} of 3`}>
              {[0, 1, 2].map((b) => (
                <span
                  key={b}
                  className="h-3 w-[5px] rounded-[1px]"
                  style={{ background: color, opacity: b < impact ? 1 : 0.22 }}
                />
              ))}
            </span>
          </span>
          <span
            className="block overflow-hidden pl-6 text-[11.5px] leading-relaxed text-caption transition-[max-height] duration-300"
            style={{ maxHeight: open === i ? 52 : 0 }}
          >
            {detail}
          </span>
        </button>
      ))}
    </div>
  )
}
