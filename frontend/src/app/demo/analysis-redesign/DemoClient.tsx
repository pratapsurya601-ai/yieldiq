"use client"

// Throwaway design-preview assembly for the v3 analysis-page redesign.
// Source of truth: docs/ANALYSIS_PAGE_TARGET_ARCHITECTURE.md §7 and the
// four locked mockups in docs/redesign_mockups/. Mock data only.
import { useState } from "react"

import ActionRail from "./ActionRail"
import ChromeHeader from "./ChromeHeader"
import DecisionBox from "./DecisionBox"
import JumpNav from "./JumpNav"
import SectionAnswer from "./SectionAnswer"
import SectionBusiness from "./SectionBusiness"
import SectionDividends from "./SectionDividends"
import SectionFinancials from "./SectionFinancials"
import SectionForecast from "./SectionForecast"
import SectionNews from "./SectionNews"
import SectionOwnership from "./SectionOwnership"
import SectionPeers from "./SectionPeers"
import SectionPrice from "./SectionPrice"
import SectionQuarterly from "./SectionQuarterly"
import SectionRisk from "./SectionRisk"
import SectionThesis from "./SectionThesis"
import SectionValuation from "./SectionValuation"

export type DemoTier = "free" | "pro"

export default function DemoClient() {
  const [tier, setTier] = useState<DemoTier>("free")

  return (
    <div className="mx-auto max-w-[1060px] px-3 pb-16 md:px-5">
      <DemoStyles />

      {/* A · demo banner + M · demo-only tier preview toggle */}
      <div className="mb-3 mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-tone-warn-bd bg-tone-warn-bg px-3.5 py-2">
        <span className="text-[12.5px] font-medium text-tone-warn-fg">
          Design preview — illustrative data, not live
        </span>
        <span className="inline-flex items-center gap-1.5 text-[11.5px] text-tone-warn-fg">
          Preview as:
          <span className="inline-flex overflow-hidden rounded-full border border-tone-warn-bd">
            <TierButton on={tier === "free"} onClick={() => setTier("free")}>
              Free
            </TierButton>
            <TierButton on={tier === "pro"} onClick={() => setTier("pro")}>
              Pro
            </TierButton>
          </span>
        </span>
      </div>

      <ChromeHeader />
      <JumpNav />
      <DecisionBox />
      <SectionPrice />
      <SectionAnswer />
      <SectionThesis />
      <SectionBusiness />
      <SectionFinancials />
      <SectionDividends />
      <SectionQuarterly />
      <SectionValuation tier={tier} />
      <SectionForecast />
      <SectionRisk />
      <SectionOwnership />
      <SectionPeers />
      <SectionNews />
      <ActionRail />
    </div>
  )
}

function TierButton({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={`px-2.5 py-0.5 text-[11px] font-medium transition-colors ${
        on ? "bg-warning text-surface" : "bg-transparent text-tone-warn-fg"
      }`}
    >
      {children}
    </button>
  )
}

/**
 * Demo-local keyframes (marching ants, live-pulse dot, Pulse-band
 * breathing). Scoped names; the global prefers-reduced-motion
 * kill-switch in globals.css also applies, and the media block below
 * doubles up for safety.
 */
function DemoStyles() {
  return (
    <style>{`
@keyframes demo-march { to { stroke-dashoffset: -11; } }
@keyframes demo-live-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .3; } }
@keyframes demo-breathe { 0%, 100% { fill-opacity: .55; } 50% { fill-opacity: .65; } }
.demo-march { stroke-dasharray: 6 5; animation: demo-march 1.1s linear infinite; }
.demo-live-pulse { animation: demo-live-pulse 1.9s ease-in-out infinite; }
.demo-breathe { animation: demo-breathe 5.6s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .demo-march, .demo-live-pulse, .demo-breathe { animation: none !important; }
}
`}</style>
  )
}
