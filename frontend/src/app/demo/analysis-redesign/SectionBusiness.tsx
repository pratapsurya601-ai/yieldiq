"use client"

// F · §3 Business (02 supersedes 01) — money-machine flow with
// marching-ant arrows, tappable revenue treemap with ₹ values, moat chips.
import { useState } from "react"
import { CircleCheck, History, Landmark, PiggyBank, Users } from "lucide-react"

import { MOAT_CHIPS, SEGMENTS } from "./data"
import { seg, useStageClock } from "./hooks"
import { DEMO_COLORS, TOKENS } from "./theme"
import { Muted, Ribbon, Section, Subh, TwoCol } from "./ui"

const CHIP_ICONS: Record<string, React.ReactNode> = {
  bank: <Landmark size={14} aria-hidden="true" />,
  piggy: <PiggyBank size={14} aria-hidden="true" />,
  history: <History size={14} aria-hidden="true" />,
  users: <Users size={14} aria-hidden="true" />,
}

export default function SectionBusiness() {
  const { ref, elapsed } = useStageClock(1200, 0.2)
  const [sel, setSel] = useState(0)

  return (
    <Section
      id="sec-3"
      num="3"
      title="Business — how it makes money"
      innerRef={ref}
      ribbon={
        <Ribbon tone="good" icon={<CircleCheck size={13} aria-hidden="true" />}>
          High confidence
        </Ribbon>
      }
    >
      <Subh>The machine — borrow low, lend high</Subh>
      <svg
        viewBox="0 0 560 116"
        width="100%"
        role="img"
        aria-label="Deposits of 25.6 lakh crore rupees at about 5.5 percent cost flow through a 3.6 percent net interest margin into advances of 25.4 lakh crore at about 9.1 percent yield."
        className="block"
      >
        <rect x={16} y={24} width={158} height={60} rx={9} fill="rgba(55,138,221,0.14)" stroke={DEMO_COLORS.blue} strokeWidth={1} />
        <text x={95} y={44} textAnchor="middle" fontSize={11} fill={DEMO_COLORS.blueDark} fontWeight={500}>
          DEPOSITS
        </text>
        <text x={95} y={61} textAnchor="middle" fontSize={14} fontWeight={500} fill={TOKENS.ink} className="num">
          ₹25.6L cr
        </text>
        <text x={95} y={76} textAnchor="middle" fontSize={10} fill={TOKENS.caption}>
          cost ~5.5%
        </text>
        <line className="demo-march" x1={174} y1={54} x2={225} y2={54} stroke={DEMO_COLORS.gray} strokeWidth={2} />
        <polygon points="225,49 235,54 225,59" fill={DEMO_COLORS.gray} />
        <rect x={237} y={24} width={120} height={60} rx={9} fill="rgba(29,158,117,0.16)" stroke={DEMO_COLORS.teal} strokeWidth={1.2} />
        <text x={297} y={44} textAnchor="middle" fontSize={11} fill={DEMO_COLORS.tealDark} fontWeight={500}>
          THE SPREAD
        </text>
        <text x={297} y={63} textAnchor="middle" fontSize={16} fontWeight={500} fill={DEMO_COLORS.tealDark} className="num">
          NIM 3.6%
        </text>
        <text x={297} y={77} textAnchor="middle" fontSize={10} fill={TOKENS.caption}>
          the profit engine
        </text>
        <line className="demo-march" x1={357} y1={54} x2={408} y2={54} stroke={DEMO_COLORS.gray} strokeWidth={2} />
        <polygon points="408,49 418,54 408,59" fill={DEMO_COLORS.gray} />
        <rect x={420} y={24} width={124} height={60} rx={9} fill="rgba(136,135,128,0.13)" stroke={TOKENS.border} strokeWidth={1} />
        <text x={482} y={44} textAnchor="middle" fontSize={11} fill={TOKENS.caption} fontWeight={500}>
          ADVANCES
        </text>
        <text x={482} y={61} textAnchor="middle" fontSize={14} fontWeight={500} fill={TOKENS.ink} className="num">
          ₹25.4L cr
        </text>
        <text x={482} y={76} textAnchor="middle" fontSize={10} fill={TOKENS.caption}>
          yield ~9.1%
        </text>
        <text x={280} y={108} textAnchor="middle" fontSize={10.5} fill={TOKENS.caption}>
          38% of deposits are low-cost CASA — that {"che" + "ap"} funding IS the moat
        </text>
      </svg>

      <TwoCol align="stretch" className="mt-3.5">
        <div>
          <Subh>
            Where revenue comes from — FY25 total income ₹1.66L cr{" "}
            <span className="font-normal text-caption">· tap a segment</span>
          </Subh>
          <div className="flex h-[182px] gap-1.5">
            <Tile i={0} sel={sel} onSel={setSel} elapsed={elapsed} />
            <div className="flex flex-col gap-1.5" style={{ flex: 38 }}>
              <Tile i={1} sel={sel} onSel={setSel} elapsed={elapsed} />
              <Tile i={2} sel={sel} onSel={setSel} elapsed={elapsed} />
            </div>
          </div>
          <Muted className="mt-2 min-h-[34px]">{SEGMENTS[sel].caption}</Muted>
        </div>

        <div>
          <Subh>Why it defends the spread</Subh>
          <div className="flex flex-col gap-2">
            {MOAT_CHIPS.map((chip) => (
              <span
                key={chip.icon}
                className="inline-flex items-center gap-1.5 self-start rounded-full bg-raised px-3 py-1 text-[11.5px] text-ink"
              >
                <span className="text-success">{CHIP_ICONS[chip.icon]}</span>
                {chip.text}
              </span>
            ))}
          </div>
          <Muted className="mt-2.5">
            Fees and cards add ~₹45k cr of other income on top of the lending spread — see the
            bridge below.
          </Muted>
        </div>
      </TwoCol>
    </Section>
  )
}

function Tile({
  i,
  sel,
  onSel,
  elapsed,
}: {
  i: number
  sel: number
  onSel: (i: number) => void
  elapsed: number
}) {
  const s = SEGMENTS[i]
  const pop = seg(elapsed, 200 + i * 140, 500)
  const on = sel === i
  return (
    <button
      type="button"
      onClick={() => onSel(i)}
      aria-pressed={on}
      className={`flex cursor-pointer flex-col items-start justify-end rounded-lg px-3 py-2.5 text-left transition-shadow ${
        on ? "outline outline-2 -outline-offset-2 outline-ink" : ""
      }`}
      style={{
        flex: i === 0 ? 62 : s.flex,
        background: s.bg,
        color: s.fg,
        transform: `scale(${(0.9 + 0.1 * pop).toFixed(3)})`,
        opacity: pop,
      }}
    >
      <span className="text-[12.5px] font-medium">{s.name}</span>
      <span className="num mt-px text-[15px] font-medium">{s.value}</span>
      <span className="text-[10.5px] opacity-85">{s.share}</span>
    </button>
  )
}
