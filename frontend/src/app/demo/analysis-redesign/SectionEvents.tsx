"use client"

// Events — a dedicated corporate-actions calendar (a retail gap). A
// date-led timeline of results, dividends, the AGM and board meetings,
// split into Upcoming / Recent with a status pill on each and a
// next-event countdown ribbon. Deliberately a DIFFERENT shape from the
// §9 news feed (which is unscheduled headlines, tiered by source) — this
// is the scheduled, dated calendar. Mock data only; SSR-safe.
import { CalendarClock, CalendarDays, Coins, Landmark } from "lucide-react"

import { seg, useStageClock } from "./hooks"
import { DEMO_COLORS } from "./theme"
import { Muted, Ribbon, Section, Subh } from "./ui"

type EventType = "results" | "dividend" | "agm" | "meeting"
type EventStatus = "Confirmed" | "Tentative" | "Completed"

interface CorpEvent {
  date: string
  type: EventType
  title: string
  detail: string
  status: EventStatus
}

const TYPE_META: Record<EventType, { color: string; Icon: typeof CalendarDays }> = {
  results: { color: DEMO_COLORS.blue, Icon: CalendarDays },
  dividend: { color: DEMO_COLORS.teal, Icon: Coins },
  agm: { color: DEMO_COLORS.purple, Icon: Landmark },
  meeting: { color: DEMO_COLORS.amber, Icon: CalendarClock },
}

const STATUS_CLS: Record<EventStatus, string> = {
  Confirmed: "bg-tone-good-bg text-tone-good-fg",
  Tentative: "bg-tone-warn-bg text-tone-warn-fg",
  Completed: "bg-raised text-caption",
}

const UPCOMING: CorpEvent[] = [
  { date: "19 Jul", type: "meeting", title: "Board meeting — Q1 FY27 results", detail: "Board to consider and approve Q1 results", status: "Confirmed" },
  { date: "24 Jul", type: "dividend", title: "Ex-dividend · ₹22 / share", detail: "Record date 25 Jul · final dividend for FY26", status: "Confirmed" },
  { date: "08 Aug", type: "agm", title: "30th Annual General Meeting", detail: "Mumbai · resolutions incl. auditor reappointment", status: "Confirmed" },
  { date: "12 Aug", type: "dividend", title: "Dividend pay date · ₹22 / share", detail: "Credit to shareholders on record as of 25 Jul", status: "Tentative" },
]

const RECENT: CorpEvent[] = [
  { date: "19 Apr", type: "results", title: "Q4 FY26 results", detail: "Net profit ₹17.6k cr · NII ₹32k cr", status: "Completed" },
  { date: "02 Apr", type: "dividend", title: "Final dividend declared · ₹22 / share", detail: "Subject to AGM approval", status: "Completed" },
  { date: "15 Jan", type: "results", title: "Q3 FY26 results", detail: "Net profit ₹16.7k cr · NII ₹31k cr", status: "Completed" },
]

export default function SectionEvents() {
  const { ref, elapsed } = useStageClock(1400, 0.15)

  return (
    <Section
      id="sec-events"
      title="Events & corporate-actions calendar"
      innerRef={ref}
      ribbon={
        <Ribbon tone="info" icon={<CalendarClock size={13} aria-hidden="true" />}>
          Next event in 36 days
        </Ribbon>
      }
    >
      <Subh>Upcoming</Subh>
      <div className="mb-4">
        {UPCOMING.map((e, i) => (
          <EventRow key={e.date + e.title} ev={e} enter={seg(elapsed, 120 + i * 110, 420)} last={i === UPCOMING.length - 1} />
        ))}
      </div>

      <Subh className="text-caption">Recent</Subh>
      <div>
        {RECENT.map((e, i) => (
          <EventRow key={e.date + e.title} ev={e} enter={seg(elapsed, 560 + i * 110, 420)} last={i === RECENT.length - 1} dim />
        ))}
      </div>

      <Muted className="mt-3">
        Dates from exchange filings and the company calendar; the pay date is tentative until the record date is fixed.
      </Muted>
    </Section>
  )
}

function EventRow({ ev, enter, last, dim = false }: { ev: CorpEvent; enter: number; last: boolean; dim?: boolean }) {
  const { color, Icon } = TYPE_META[ev.type]
  return (
    <div
      className="relative flex items-start gap-3 pb-3.5"
      style={{ opacity: dim ? 0.55 + enter * 0.45 : enter, transform: `translateY(${(7 * (1 - enter)).toFixed(1)}px)` }}
    >
      {/* connector spine */}
      {!last && <div className="absolute bottom-0 left-[39px] top-7 w-px bg-border/70" aria-hidden="true" />}

      {/* date chip */}
      <div className="w-8 shrink-0 pt-1 text-right">
        <div className="num text-[12.5px] font-medium leading-none text-ink">{ev.date.split(" ")[0]}</div>
        <div className="text-[10px] uppercase tracking-wide text-caption">{ev.date.split(" ")[1]}</div>
      </div>

      {/* type icon */}
      <div
        className="z-[1] flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border/60"
        style={{ background: "var(--color-surface)" }}
      >
        <Icon size={14} aria-hidden="true" style={{ color }} />
      </div>

      {/* title + detail */}
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="text-[13px] font-medium leading-snug text-ink">{ev.title}</div>
        <div className="mt-px text-[11.5px] leading-snug text-caption">{ev.detail}</div>
      </div>

      {/* status pill */}
      <span className={`mt-1 shrink-0 rounded-full px-2 py-[2px] text-[10.5px] font-medium ${STATUS_CLS[ev.status]}`}>
        {ev.status}
      </span>
    </div>
  )
}
