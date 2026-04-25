"use client"

import Prism from "@/components/prism/Prism"
import type { PrismData } from "@/components/prism/types"

const FALLBACK_PRISM: PrismData = {
  ticker: "SAMPLE",
  company_name: "Sample Co.",
  verdict_band: "undervalued",
  verdict_label: "Below Fair Value",
  overall: 7.4,
  refraction_index: 1.2,
  pulse_velocity_hz: 0.33,
  disclaimer: "Model estimate. Not investment advice.",
  pillars: [
    { key: "pulse", score: 7.2, label: "Positive", why: "Steady momentum.", data_limited: false, weight: 0.10 },
    { key: "quality", score: 8.1, label: "Strong", why: "High ROE, low debt.", data_limited: false, weight: 0.22 },
    { key: "moat", score: 7.0, label: "Moderate", why: "Brand + scale.", data_limited: false, weight: 0.18 },
    { key: "safety", score: 7.5, label: "Strong", why: "Comfortable coverage.", data_limited: false, weight: 0.15 },
    { key: "growth", score: 6.4, label: "Moderate", why: "Revenue expanding.", data_limited: false, weight: 0.15 },
    { key: "value", score: 7.8, label: "Strong", why: "Trading below estimate.", data_limited: false, weight: 0.20 },
  ],
  sector_medians: {},
}

interface StepExplainerProps {
  referenceData?: PrismData | null
  onFinish: () => void
}

const BULLETS = [
  {
    icon: "🔍",
    title: "6 pillars",
    body: "Pulse, Quality, Moat, Safety, Growth, Value — each scored 0 to 10.",
  },
  {
    icon: "💡",
    title: "Wider = better",
    body: "Each lens\u2019s width is that pillar\u2019s score. Narrow means low, wide means high.",
  },
  {
    icon: "🎯",
    title: "The beam converges",
    body: "Into one composite score and a plain-English verdict.",
  },
]

export default function StepExplainer({ referenceData, onFinish }: StepExplainerProps) {
  const data = referenceData ?? FALLBACK_PRISM

  return (
    <div className="flex flex-col min-h-[calc(100vh-56px)] px-5 pb-8">
      <header className="pt-6 pb-4">
        <h1 className="font-editorial text-3xl sm:text-4xl text-ink leading-tight">
          Here&apos;s how it works
        </h1>
        <p className="mt-2 text-base text-body">
          The Prism, explained in 30 seconds.
        </p>
      </header>

      <div className="flex justify-center py-4">
        <Prism data={data} firstView={false} size={220} mode="signature" />
      </div>

      <ul className="space-y-4 mt-2">
        {BULLETS.map((b) => (
          <li key={b.title} className="flex items-start gap-3">
            <span
              aria-hidden="true"
              className="w-10 h-10 rounded-full bg-surface border border-border flex items-center justify-center text-lg flex-shrink-0"
            >
              {b.icon}
            </span>
            <div className="min-w-0">
              <p className="font-semibold text-ink">{b.title}</p>
              <p className="text-sm text-body mt-0.5 leading-snug">{b.body}</p>
            </div>
          </li>
        ))}
      </ul>

      <p className="text-xs text-caption mt-6 text-center">
        Model estimate. Not investment advice.
      </p>

      <div className="pt-6 mt-auto sticky bottom-0 bg-bg">
        <button
          type="button"
          onClick={onFinish}
          className="w-full min-h-[52px] rounded-full bg-ink text-bg font-semibold text-base hover:opacity-90 active:scale-[0.99] transition-all"
        >
          Start exploring →
        </button>
        <p className="text-center mt-3">
          <span className="text-xs text-caption">
            Tip: tap &ldquo;Tell me the story&rdquo; on any stock to hear the narration.
          </span>
        </p>
      </div>
    </div>
  )
}
