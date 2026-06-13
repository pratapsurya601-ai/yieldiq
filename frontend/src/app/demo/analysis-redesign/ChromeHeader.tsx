"use client"

// B · Chrome — ticker identity band, provenance bar (04 gap closure)
// and the 52-week dumbbell with its sliding marker.
import TickerAvatar from "@/components/common/TickerAvatar"

import { seg, useStageClock } from "./hooks"
import { DEMO_COLORS } from "./theme"
import { Muted } from "./ui"

const WEEK52_POS = 74.5 // (1684 − 1363) / (1794 − 1363)

// Quick-stats strip — the scannable factual header retail expects up top.
const QUICK_STATS: { label: string; value: string }[] = [
  { label: "P/E", value: "18.5" },
  { label: "P/B", value: "2.6" },
  { label: "ROE", value: "16.1%" },
  { label: "Div yield", value: "1.1%" },
  { label: "ROA", value: "2.0%" },
  { label: "Beta", value: "0.92" },
]

export default function ChromeHeader() {
  const { ref, elapsed } = useStageClock(1200, 0.1)
  const fill = WEEK52_POS * seg(elapsed, 0, 1000)

  return (
    <div ref={ref}>
      {/* Identity band */}
      <div className="flex flex-wrap items-center gap-3.5 px-1 pb-4 pt-0.5">
        <TickerAvatar ticker="HDFCBANK" size="lg" sector="banking" className="rounded-lg" />
        <div className="min-w-[200px] flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[20px] font-medium tracking-tight text-ink">HDFC Bank Ltd</span>
            <span className="rounded-md border border-border px-1.5 py-0.5 text-[11px] text-caption">
              HDFCBANK · NSE
            </span>
          </div>
          <Muted className="mt-0.5">Private sector bank · Financials · Large cap</Muted>
        </div>
        <div className="text-right">
          <div className="num text-[22px] font-medium text-ink">
            <span
              className="demo-live-pulse mr-1.5 inline-block h-[7px] w-[7px] rounded-full align-middle"
              style={{ background: DEMO_COLORS.teal }}
              aria-hidden="true"
            />
            ₹1,684
            <span className="ml-1.5 text-[13px] font-normal text-success">+0.8%</span>
          </div>
          <Muted>Market cap ₹12.8 lakh cr</Muted>
        </div>
      </div>

      {/* Quick-stats strip — scannable factual header */}
      <div className="mb-3 grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-border/70 bg-border/70 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_20px_-12px_rgba(15,23,42,0.10)] sm:grid-cols-6">
        {QUICK_STATS.map((s) => (
          <div key={s.label} className="bg-raised px-3 py-2.5 transition-colors hover:bg-surface">
            <div className="text-[10.5px] text-caption">{s.label}</div>
            <div className="num mt-px text-[15.5px] font-semibold text-ink">{s.value}</div>
          </div>
        ))}
      </div>

      {/* Provenance bar — trust at a glance */}
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-xl border border-border/60 bg-raised px-3.5 py-2 text-[12px] text-caption shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_20px_-12px_rgba(15,23,42,0.10)]">
        <span>
          <Dot color={DEMO_COLORS.teal} pulse />
          Price live · NSE
        </span>
        <span>
          <Dot color={DEMO_COLORS.blue} />
          Financials FY25 · filed Apr 2026
        </span>
        <span>
          <Dot color={DEMO_COLORS.purple} />
          Model updated 11 Jun 2026
        </span>
        <span className="ml-auto">
          Computed 2h ago ·{" "}
          <button type="button" className="cursor-pointer text-tone-info-fg hover:underline">
            recompute
          </button>
        </span>
      </div>

      {/* 52-week dumbbell */}
      <div className="mb-3.5 flex flex-wrap items-center gap-3.5 px-1">
        <Muted className="whitespace-nowrap">52-week range</Muted>
        <div className="relative h-[26px] min-w-[220px] flex-1">
          <div className="absolute left-0 right-0 top-[11px] h-1 rounded-sm bg-border/70" />
          <div
            className="absolute top-[11px] h-1 rounded-sm bg-caption/50"
            style={{ width: `${fill}%` }}
          />
          <span className="absolute left-0 top-[9px] h-2 w-2 rounded-full bg-caption" />
          <span className="absolute right-0 top-[9px] h-2 w-2 rounded-full bg-caption" />
          <span
            className="absolute top-[6px] h-3.5 w-3.5 rounded-full border-[2.5px] border-surface bg-ink"
            style={{ left: `calc(${fill}% - 7px)` }}
          />
        </div>
        <Muted className="num whitespace-nowrap">
          ₹1,363 — <span className="font-medium text-ink">₹1,684</span> — ₹1,794
        </Muted>
      </div>
    </div>
  )
}

function Dot({ color, pulse = false }: { color: string; pulse?: boolean }) {
  return (
    <span
      className={`mr-1.5 inline-block h-2 w-2 rounded-full align-[-1px] ${pulse ? "demo-live-pulse" : ""}`}
      style={{ background: color }}
      aria-hidden="true"
    />
  )
}
