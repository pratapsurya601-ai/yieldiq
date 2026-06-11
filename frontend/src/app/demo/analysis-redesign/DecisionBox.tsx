"use client"

// C · Decision Box (fast lane) — verdict pill, MoS hero count-up,
// sequenced fair-value bar (blue price fill THEN green MoS zone THEN
// marker), live alert slider, pillar inspector slot fed by Spectrum taps.
import { useState } from "react"
import { TrendingUp } from "lucide-react"

import { FAIR_VALUE, MOS_PCT, SPECTRUM_AXES, SPECTRUM_NARRATIVE } from "./data"
import { inr, seg, useStageClock } from "./hooks"
import Spectrum from "./Spectrum"
import { Muted, Subh } from "./ui"

export default function DecisionBox() {
  const { ref, elapsed } = useStageClock(2600, 0.12)
  const [alertPct, setAlertPct] = useState(20)
  const [picked, setPicked] = useState<number | null>(null)
  const [peerOn, setPeerOn] = useState(false)

  // The mockup auto-selects the VALUE band once the unfold lands —
  // derived in render (no effect) so a user tap always wins.
  const selected = picked !== null ? picked : elapsed >= 2500 ? 5 : null

  const mosNum = Math.round(MOS_PCT * seg(elapsed, 0, 1200))
  const blueW = 83.8 * seg(elapsed, 0, 1050)
  const greenScale = seg(elapsed, 1050, 550)
  const markOn = elapsed >= 1600
  const axis = selected !== null ? SPECTRUM_AXES[selected] : null

  return (
    <section ref={ref} className="mb-3.5 rounded-2xl border-2 border-tone-info-bd bg-surface px-4 py-4 md:px-5">
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
        {/* Left — the ten-second answer */}
        <div>
          <div className="mb-2.5 inline-flex items-center gap-1.5 rounded-full bg-tone-good-bg px-3 py-1 text-[13px] text-tone-good-fg">
            <TrendingUp size={15} aria-hidden="true" />
            Undervalued
          </div>
          <div className="flex items-baseline gap-2">
            <span className="num text-[40px] font-medium leading-none text-success">{mosNum}%</span>
            <Muted>below fair value</Muted>
          </div>

          {/* Sequenced fair-value bar */}
          <div className="relative mb-1.5 mt-4 h-[30px] overflow-hidden rounded-lg bg-raised">
            <div className="absolute bottom-0 left-0 top-0 bg-tone-info-bg" style={{ width: `${blueW}%` }} />
            <div
              className="absolute bottom-0 top-0 origin-left bg-tone-good-bg"
              style={{ left: "83.8%", width: "16.2%", transform: `scaleX(${greenScale})` }}
            />
            <div
              className="absolute bottom-0 top-0 w-0.5 bg-ink transition-opacity duration-300"
              style={{ left: "83.8%", opacity: markOn ? 1 : 0 }}
            />
          </div>
          <div className="flex justify-between text-[12px] text-caption">
            <span className="num">
              <span className="font-medium text-ink">₹1,684</span> price
            </span>
            <span className="num">
              <span className="font-medium text-success">₹2,010</span> fair value
            </span>
          </div>

          {/* Live alert slider */}
          <div className="mt-3.5 flex items-center gap-2.5">
            <label htmlFor="demo-alert" className="whitespace-nowrap text-[12.5px] text-caption">
              Alert at
            </label>
            <input
              id="demo-alert"
              type="range"
              min={10}
              max={35}
              step={1}
              value={alertPct}
              onChange={(e) => setAlertPct(Number(e.target.value))}
              className="flex-1 accent-[var(--color-brand)]"
            />
            <span className="num min-w-[34px] text-[12.5px] font-medium text-ink">{alertPct}%</span>
          </div>
          <Muted className="num mt-1 text-[12px]">
            Notify me when price falls to {inr(FAIR_VALUE * (1 - alertPct / 100))}.
          </Muted>

          {/* Pillar inspector slot (fed by Spectrum taps) */}
          <div
            className="mt-3.5 min-h-[96px] rounded-lg border-l-[3px] bg-raised px-3.5 py-2.5 transition-colors duration-200"
            style={{ borderLeftColor: axis ? axis.c : "transparent" }}
            aria-live="polite"
          >
            {axis ? (
              <>
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-medium tracking-wide text-ink">{axis.k}</span>
                  <span className="num text-[16px] font-medium" style={{ color: axis.d }}>
                    {axis.s.toFixed(1)}
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10.5px] ${
                      axis.tone === "good" ? "bg-tone-good-bg text-tone-good-fg" : "bg-tone-warn-bg text-tone-warn-fg"
                    }`}
                  >
                    {axis.lab}
                  </span>
                </div>
                <div className="mb-1.5 inline-block rounded-full bg-tone-info-bg px-2.5 py-0.5 text-[11px] text-tone-info-fg">
                  {axis.chip}
                </div>
                <div className="text-[12px] leading-snug text-caption">{axis.why}</div>
              </>
            ) : (
              <Muted className="text-[11.5px]">Tap a Spectrum band to inspect that pillar.</Muted>
            )}
          </div>
        </div>

        {/* Right — the Spectrum */}
        <div className="text-center">
          <div className="mb-0.5 flex items-center justify-between gap-2">
            <Subh className="m-0">YieldIQ Spectrum</Subh>
            <button
              type="button"
              onClick={() => setPeerOn((v) => !v)}
              aria-pressed={peerOn}
              className={`rounded-full border px-2.5 py-[3px] text-[11px] transition-colors ${
                peerOn
                  ? "border-tone-info-bd bg-tone-info-bg text-tone-info-fg"
                  : "border-border bg-transparent text-caption hover:border-caption/60"
              }`}
            >
              + ICICIBANK
            </button>
          </div>
          <Spectrum elapsed={elapsed} selected={selected} onSelect={setPicked} peerOn={peerOn} />
          <div className="flex justify-center gap-4 text-[11px] text-caption">
            <span>
              <span className="mr-1.5 inline-block h-2.5 w-0.5 bg-caption align-[-2px] opacity-70" />
              sector median
            </span>
            {peerOn && (
              <span>
                <span className="mr-1.5 inline-block w-4 border-t-[1.5px] border-dashed border-caption align-[3px]" />
                ICICIBANK
              </span>
            )}
          </div>
          <div
            className="mt-1 text-[12px] text-ink transition-opacity duration-500"
            style={{ opacity: elapsed >= 2500 ? 1 : 0 }}
          >
            {SPECTRUM_NARRATIVE}
          </div>
        </div>
      </div>
    </section>
  )
}
