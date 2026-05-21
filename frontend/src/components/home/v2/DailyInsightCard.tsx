"use client"
// Daily Insight — Day-74 (2026-05-21): rotating tip array.
//
// Audit 2026-05-20 flagged the slot as "still a screener hint, same
// string for weeks". Until the nightly rule engine (TODO below) ships,
// rotate through 7 educational tips — same day-of-year-mod-7 pattern
// as the Discover methodology spotlight (see discover/page.tsx
// pickTodayTip around line 85). Stable within a day, rotates weekly.
//
// Each tip must use SEBI-compliant vocabulary only. See
// backend/services/analysis/sebi_filter.py for the canonical banned-
// word list. "Consider", "look at", "compare with" are the only
// call-to-action verbs allowed in tip text.
//
// TODO: build a nightly rule engine (backend cron) that scans
// analysis_cache and emits 1-3 factual deltas, e.g. count of IT names
// that crossed into a higher MoS band, sector MoS shifts on latest
// quarterly results. Expose via /api/v1/insights/daily. Until that
// exists, this static rotation keeps the slot fresh.

import Link from "next/link"
import { Sparkles } from "lucide-react"

interface DailyTip {
  text: string
  href: string
  cta: string
}

const DAILY_TIPS: DailyTip[] = [
  {
    // MoS thresholds across cycles
    text:
      "Margin of Safety is not one fixed number. For cyclicals near a trough, 35-40% MoS leaves room for an earnings reset; for steady compounders, 15-20% can be enough.",
    href: "/methodology#margin-of-safety",
    cta: "Read MoS methodology →",
  },
  {
    // Reverse-DCF interpretation
    text:
      "If reverse-DCF implies 18%+ FCF growth for 10 years to justify today's price, the market is pricing in best-case execution. Compare with the company's last 5-year revenue CAGR.",
    href: "/methodology#reverse-dcf",
    cta: "How reverse-DCF works →",
  },
  {
    // Confidence vs grade
    text:
      "A 'Wide' moat grade with low Confidence means the label is right but the inputs are thin. Look at the Confidence score before relying on any single grade on the page.",
    href: "/methodology#confidence",
    cta: "Confidence vs grade →",
  },
  {
    // Story-DCF / cyclical rescue
    text:
      "For cyclicals at a trough (e.g. metals after a margin crash), the Story-DCF normalisation pass replaces trailing earnings with mid-cycle margins. Consider the Story-DCF tab when trailing PAT looks distressed.",
    href: "/analysis/TATASTEEL",
    cta: "See Story-DCF on Tata Steel →",
  },
  {
    // Sector-specific WACC
    text:
      "Banks, FMCG, and capital goods don't share a discount rate. YieldIQ uses sector-median equity beta with India 10Y as the risk-free anchor — compare with how the company's own beta drifts from the sector median.",
    href: "/methodology#wacc",
    cta: "Sector WACC explained →",
  },
  {
    // Dividend coverage vs payout
    text:
      "Payout ratio (dividend / EPS) and coverage ratio (FCF / dividend) tell different stories. A 30% payout with 1.2x FCF coverage is fragile; 60% payout with 3x coverage is safer.",
    href: "/screener?preset=dividend-aristocrats",
    cta: "Dividend-safety screen →",
  },
  {
    // When DCF isn't the right model
    text:
      "DCF breaks down for early-stage IPOs, post-demerger entities with under 2 years of data, and pure financials. YieldIQ routes these through peer-multiple or appraisal frameworks — look for the 'valuation engine' tag on the page.",
    href: "/methodology#engine-selection",
    cta: "When DCF isn't the right tool →",
  },
]

function pickTodayTip(): DailyTip {
  // Day-of-year mod 7 — same pattern as discover/page.tsx pickTodayTip.
  // Stable across the calendar day, rotates weekly.
  const now = new Date()
  const start = new Date(now.getFullYear(), 0, 0)
  const diffMs = now.getTime() - start.getTime()
  const dayOfYear = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  return DAILY_TIPS[dayOfYear % DAILY_TIPS.length]
}

export default function DailyInsightCard() {
  const tip = pickTodayTip()
  return (
    <div className="bg-gradient-to-br from-brand/10 via-surface to-surface border border-brand/30 rounded-2xl p-4">
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg bg-brand/15 flex items-center justify-center flex-shrink-0">
          <Sparkles className="w-4 h-4 text-brand" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-bold uppercase tracking-widest text-brand mb-1">
            Daily insight
          </p>
          <p className="text-sm font-semibold text-ink leading-snug">
            {tip.text}
          </p>
          <Link
            href={tip.href}
            className="inline-flex items-center mt-2 text-xs font-semibold text-brand hover:underline"
          >
            {tip.cta}
          </Link>
          {/* Day-83: secondary link into the end-user help section so the
              Daily Insight slot doubles as an entry point into /help. */}
          <Link
            href="/help"
            className="block mt-1 text-[11px] text-caption hover:text-ink transition-colors"
          >
            Browse all help topics &rarr;
          </Link>
        </div>
      </div>
    </div>
  )
}

// Exported for unit tests — kept after the default export so the
// component remains the module's main export. Tests import the tip
// array and the rotation helper directly to lock in:
//   - tip count == 7
//   - rotation is day-of-year-mod-7 (stable within a day)
//   - no SEBI-banned vocabulary in any tip text
export { DAILY_TIPS, pickTodayTip }
