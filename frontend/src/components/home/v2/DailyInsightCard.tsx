"use client"
// Daily Insight — placeholder for v1.
// TODO: build a nightly rule engine (backend cron) that scans analysis_cache
// and emits 1-3 factual deltas, e.g. count of IT names that crossed into
// a higher MoS band, sector MoS shifts on latest quarterly results.
// Expose via /api/v1/insights/daily. Until that exists, we render an
// educational nudge so the slot is not visually empty.

import Link from "next/link"
import { Sparkles } from "lucide-react"

export default function DailyInsightCard() {
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
            Use the screener to find stocks with MoS &gt; 20% and Hex score ≥ 70.
          </p>
          <p className="text-xs text-body mt-1">
            Automated daily market insights coming soon.
          </p>
          <Link
            href="/screener?preset=buffett"
            className="inline-flex items-center mt-2 text-xs font-semibold text-brand hover:underline"
          >
            Run wide-moat screen →
          </Link>
        </div>
      </div>
    </div>
  )
}
