"use client"

// M(§9) · News & catalysts (04) — catalyst chips, tiered feed rail
// (T1 exchange filing > T2 national > T3 aggregator), community split pill.
import { CalendarDays, Coins, Users, Zap } from "lucide-react"

import { COMMUNITY, NEWS_FEED } from "./data"
import { seg, useStageClock } from "./hooks"
import { Muted, Ribbon, Section, Subh, TwoCol } from "./ui"

const TIER_CLS: Record<string, string> = {
  T1: "bg-tone-good-bg text-tone-good-fg",
  T2: "bg-tone-info-bg text-tone-info-fg",
  T3: "bg-raised text-caption",
}

const TIER_LABEL: Record<string, string> = {
  T1: "T1 exchange filing",
  T2: "T2 national press",
  T3: "T3 aggregator",
}

export default function SectionNews() {
  const { ref, elapsed } = useStageClock(1400, 0.2)
  const split = seg(elapsed, 100, 1000)
  const widthA = 50 + (COMMUNITY.below - 50) * split
  const widthB = 100 - widthA

  return (
    <Section
      id="sec-9"
      num="9"
      title="What's happening — news & catalysts"
      innerRef={ref}
      ribbon={
        <Ribbon tone="info" icon={<Zap size={13} aria-hidden="true" />}>
          3 catalysts ahead
        </Ribbon>
      }
    >
      <div className="mb-4 flex flex-wrap gap-2">
        <CatalystChip icon={<CalendarDays size={13} aria-hidden="true" className="text-tone-info-fg" />} text="Results · 19 Jul" />
        <CatalystChip icon={<Coins size={13} aria-hidden="true" className="text-success" />} text="Ex-dividend (est) · 24 Jul" />
        <CatalystChip icon={<Users size={13} aria-hidden="true" className="text-caption" />} text="AGM · Aug" />
      </div>

      <TwoCol align="start">
        <div>
          {NEWS_FEED.map((f, i) => {
            const enter = seg(elapsed, 250 + i * 140, 450)
            return (
              <div
                key={f.text}
                className="relative flex gap-3 pb-4"
                style={{ opacity: enter, transform: `translateY(${(8 * (1 - enter)).toFixed(1)}px)` }}
              >
                {i < NEWS_FEED.length - 1 && (
                  <div className="absolute bottom-0 left-[5px] top-3.5 w-0.5 bg-border/70" />
                )}
                <div
                  className="z-[1] mt-[3px] h-3 w-3 shrink-0 rounded-full border-2 border-surface"
                  style={{ background: f.dot }}
                />
                <div className="flex-1">
                  <div className="text-[12.5px] leading-snug text-ink">{f.text}</div>
                  <div className="mt-[3px] flex items-center gap-2">
                    <span className={`rounded-full px-1.5 py-px text-[10px] font-medium tracking-wide ${TIER_CLS[f.tier]}`}>
                      {f.tier}
                    </span>
                    <span className="text-[11px] text-caption">{f.meta}</span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        <div>
          <Subh>
            Community read <span className="font-normal text-caption">· {COMMUNITY.votes} votes</span>
          </Subh>
          <div className="flex h-[26px] overflow-hidden rounded-[7px] text-[11.5px] font-medium">
            <div
              className="flex items-center bg-tone-good-bg pl-2.5 text-tone-good-fg"
              style={{ width: `${widthA.toFixed(1)}%` }}
            >
              {COMMUNITY.below}% below FV
            </div>
            <div
              className="flex items-center justify-end bg-tone-warn-bg pr-2.5 text-tone-warn-fg"
              style={{ width: `${widthB.toFixed(1)}%` }}
            >
              {COMMUNITY.above}%
            </div>
          </div>
          <Muted className="mt-2.5">
            Source tiers:{" "}
            {(["T1", "T2", "T3"] as const).map((t) => (
              <span key={t} className={`mr-1 rounded-full px-1.5 py-px text-[10px] font-medium tracking-wide ${TIER_CLS[t]}`}>
                {TIER_LABEL[t]}
              </span>
            ))}{" "}
            — ranked so filings outrank rumours.
          </Muted>
        </div>
      </TwoCol>
    </Section>
  )
}

function CatalystChip({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-[11.5px] text-ink">
      {icon}
      {text}
    </span>
  )
}
