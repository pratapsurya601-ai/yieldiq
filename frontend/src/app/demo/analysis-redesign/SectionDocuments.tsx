"use client"

// Straight from the source — the company's OWN filings (annual reports,
// earnings-call transcripts, results, decks) plus what our AI pulled out of
// them. This is the retail "where does this come from" trust surface: it sits
// after the numbers (Financials/Quarterly) so a reader can step from a figure
// to the document it came from. Distinct from Ownership's two call quotes —
// here the focus is the document inventory + annual-report signals.
//
// Mock data only; in the real build this binds to the AR-signals + concall
// services. No charts — a list + a summary card, so it adds no new chart shape
// (§7 "no shape twice").
import {
  ExternalLink,
  FileSpreadsheet,
  FileText,
  Mic,
  Presentation,
  ShieldCheck,
  Sparkles,
} from "lucide-react"

import { seg, useStageClock } from "./hooks"
import { DEMO_COLORS } from "./theme"
import { Kpi, Muted, Ribbon, Section, Subh, TwoCol } from "./ui"

type DocKind = "transcript" | "deck" | "results" | "report"

const KIND: Record<DocKind, { Icon: typeof FileText; label: string; color: string }> = {
  transcript: { Icon: Mic, label: "Earnings call", color: DEMO_COLORS.blue },
  deck: { Icon: Presentation, label: "Presentation", color: DEMO_COLORS.purple },
  results: { Icon: FileSpreadsheet, label: "Results filing", color: DEMO_COLORS.teal },
  report: { Icon: FileText, label: "Annual report", color: DEMO_COLORS.amber },
}

const DOCS: { kind: DocKind; title: string; date: string }[] = [
  { kind: "transcript", title: "Q1 FY26 earnings-call transcript", date: "19 Jul 2025" },
  { kind: "deck", title: "Q1 FY26 investor presentation", date: "19 Jul 2025" },
  { kind: "results", title: "Q1 FY26 results — standalone + consolidated", date: "19 Jul 2025" },
  { kind: "report", title: "Annual report FY25", date: "21 Jun 2025" },
  { kind: "report", title: "Annual report FY24", date: "24 Jun 2024" },
]

// Neutral, factual takeaways the AI lifted from the latest call — deliberately
// different from the two quotes Ownership shows, so nothing repeats.
const CALL_TAKEAWAYS = [
  "Cost-to-income guided toward the high-30s as the merged base settles.",
  "Provision coverage stayed above 70%; asset quality described as stable.",
]

const AR_SIGNALS: [string, string][] = [
  ["Auditor opinion", "Unmodified"],
  ["Reported segments", "3"],
  ["Related-party deals", "Disclosed"],
  ["Contingent items", "Noted"],
]

export default function SectionDocuments() {
  const { ref, elapsed } = useStageClock(1200, 0.2)

  return (
    <Section
      id="sec-documents"
      title="Straight from the source — filings & disclosures"
      innerRef={ref}
      ribbon={
        <Ribbon tone="info" icon={<ShieldCheck size={13} aria-hidden="true" />}>
          Primary sources
        </Ribbon>
      }
    >
      <TwoCol align="start">
        <div>
          <Subh>
            On file <span className="font-normal text-caption">· {DOCS.length} most recent</span>
          </Subh>
          <div className="space-y-1.5">
            {DOCS.map((d, i) => {
              const k = KIND[d.kind]
              const enter = seg(elapsed, 200 + i * 110, 420)
              return (
                <div
                  key={d.title}
                  className="group flex items-center gap-3 rounded-lg border border-border/60 bg-raised px-3 py-2 transition-colors hover:border-tone-info-bd"
                  style={{ opacity: enter, transform: `translateY(${(8 * (1 - enter)).toFixed(1)}px)` }}
                >
                  <span
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                    style={{ background: `${k.color}1f`, color: k.color }}
                  >
                    <k.Icon size={15} aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[12.5px] font-medium text-ink">{d.title}</div>
                    <div className="text-[11px] text-caption">
                      {k.label} · {d.date}
                    </div>
                  </div>
                  <ExternalLink
                    size={14}
                    aria-hidden="true"
                    className="shrink-0 text-caption transition-colors group-hover:text-tone-info-fg"
                  />
                </div>
              )
            })}
          </div>
        </div>

        <div>
          <Subh>
            <Sparkles size={13} aria-hidden="true" className="mr-1 inline align-[-2px] text-tone-info-fg" />
            Latest call, summarised
          </Subh>
          <div className="space-y-2">
            {CALL_TAKEAWAYS.map((t, i) => {
              const enter = seg(elapsed, 360 + i * 150, 460)
              return (
                <div
                  key={t}
                  className="flex gap-2 rounded-lg border border-border/60 bg-raised px-3 py-2 text-[12.5px] leading-snug text-body"
                  style={{ opacity: enter, transform: `translateY(${(8 * (1 - enter)).toFixed(1)}px)` }}
                >
                  <span className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: DEMO_COLORS.blue }} />
                  {t}
                </div>
              )
            })}
          </div>

          <Subh className="mt-3.5">From the annual report</Subh>
          <div className="grid grid-cols-2 gap-2">
            {AR_SIGNALS.map(([label, value]) => (
              <Kpi key={label} label={label} value={value} valueClass="text-ink" />
            ))}
          </div>
        </div>
      </TwoCol>

      <Muted className="mt-3 text-[11.5px]">
        Documents are the company&apos;s own exchange filings. The call summary and annual-report signals are
        AI-extracted — always read the source document before you rely on a figure. Nothing here is advice.
      </Muted>
    </Section>
  )
}
