"use client"

/**
 * AnalysisFAQ — auto-generated Q&A section with schema.org FAQPage markup.
 *
 * Template-driven (NO LLM). Pure rules over the analysis payload. Six to
 * eight questions per ticker. The accompanying JSON-LD <script> tag is
 * eligible for Google's FAQPage rich snippet — free SEO traffic and the
 * highest-leverage move in the Alpha-Spread restyle.
 *
 * SEBI discipline: no buy / sell / target / recommend / cheap / strong
 * vocabulary in any answer text. Answers cite numbers + neutral framing
 * ("Below base case" / "Above base case" / "Aligned with base case").
 */

import { useState } from "react"
import { formatCurrency, formatPct, formatCompanyName } from "@/lib/utils"
import type { AnalysisResponse } from "@/types/api"

interface FAQItem {
  q: string
  a: string
  chip?: string
}

interface Props {
  data: AnalysisResponse
}

function mosLabel(mos: number | null | undefined): string {
  if (mos == null || !Number.isFinite(mos)) return "Unavailable"
  if (mos >= 25) return "Below base case"
  if (mos >= 10) return "Modestly below base case"
  if (mos >= -10) return "Aligned with base case"
  if (mos >= -25) return "Modestly above base case"
  return "Above base case"
}

function piotroskiLabel(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return "Unavailable"
  if (score >= 7) return "Strong financial signals"
  if (score >= 4) return "Mixed financial signals"
  return "Weak financial signals"
}

function moatExplain(moat: string | null | undefined): string {
  switch (moat) {
    case "Wide":
      return "Durable structural advantages — pricing power, scale, or switching costs."
    case "Moderate":
      return "Some structural advantage but less defensible than a wide moat."
    case "Narrow":
      return "Limited durable advantage; competitors can erode the position over time."
    case "None":
      return "No durable competitive advantage identified."
    case "N/A (Financial)":
      return "Moat framework not applied to banks / NBFCs; use bank-native KPIs instead."
    default:
      return "Not assessed."
  }
}

function buildFAQ(data: AnalysisResponse): FAQItem[] {
  const { company, valuation, quality, insights, scenarios } = data
  const name = formatCompanyName(company.company_name)
  const ticker = company.ticker.replace(".NS", "").replace(".BO", "")
  const currency = company.currency
  const cur = (v: number) => formatCurrency(v, currency, company.ticker)
  const items: FAQItem[] = []

  // 1 — Fair value
  if (valuation.fair_value > 0) {
    const bear = scenarios?.bear?.iv ?? valuation.bear_case
    const bull = scenarios?.bull?.iv ?? valuation.bull_case
    items.push({
      q: `What is ${name}'s fair value?`,
      a: `${cur(valuation.fair_value)} (DCF base case). Bear scenario ${cur(bear)}, bull scenario ${cur(bull)}.`,
      chip: `Fair Value: ${cur(valuation.fair_value)}`,
    })
  }

  // 2 — Margin of safety
  if (
    valuation.margin_of_safety != null &&
    Number.isFinite(valuation.margin_of_safety) &&
    valuation.fair_value > 0
  ) {
    const mos = valuation.margin_of_safety
    const direction =
      valuation.current_price < valuation.fair_value ? "below" : "above"
    items.push({
      q: `Is ${name} below or above its base-case fair value?`,
      a: `${mosLabel(mos)}. Margin of safety ${formatPct(mos)}. Current price ${cur(valuation.current_price)} ${direction} base-case fair value ${cur(valuation.fair_value)}.`,
      chip: `MoS: ${formatPct(mos)}`,
    })
  }

  // 3 — Revenue CAGR
  const cagr3 = quality.revenue_cagr_3y
  if (cagr3 != null && Number.isFinite(cagr3)) {
    const pct = cagr3 * 100
    items.push({
      q: `What is ${name}'s 3-year revenue CAGR?`,
      a: `${pct.toFixed(1)}% over the trailing 3 fiscal years.`,
      chip: `3y CAGR: ${pct.toFixed(1)}%`,
    })
  }

  // 4 — Moat
  if (quality.moat) {
    items.push({
      q: `What is ${name}'s economic moat?`,
      a: `${quality.moat}. ${moatExplain(quality.moat)}`,
      chip: `Moat: ${quality.moat}`,
    })
  }

  // 5 — Dividend yield
  const div = insights?.dividend
  if (div && div.has_dividends && div.current_yield_pct != null) {
    const dps = div.dividend_rate_per_share
    const years = div.consecutive_years
    const dpsText = dps != null ? `${cur(dps)}/share, ` : ""
    const yearsText = years > 0 ? `paid ${years} consecutive year${years === 1 ? "" : "s"}.` : "history available."
    items.push({
      q: `What is ${name}'s dividend yield?`,
      a: `${div.current_yield_pct.toFixed(2)}%. ${dpsText}${yearsText}`,
      chip: `Yield: ${div.current_yield_pct.toFixed(2)}%`,
    })
  }

  // 6 — Red flags
  const flagCount = insights?.red_flag_count ?? insights?.red_flags_structured?.length ?? 0
  items.push({
    q: `Does YieldIQ flag any red flags for ${name}?`,
    a:
      flagCount === 0
        ? "No red flags raised by the current screen."
        : `${flagCount} red flag${flagCount === 1 ? "" : "s"} raised. See the Red Flags panel for detail.`,
    chip: `Red Flags: ${flagCount}`,
  })

  // 7 — Piotroski
  if (
    quality.piotroski_score != null &&
    Number.isFinite(quality.piotroski_score) &&
    quality.piotroski_score > 0
  ) {
    items.push({
      q: `What is ${name}'s Piotroski F-Score?`,
      a: `${quality.piotroski_score}/9 — ${piotroskiLabel(quality.piotroski_score)}.`,
      chip: `F-Score: ${quality.piotroski_score}/9`,
    })
  }

  // 8 — Under-review explainer (conditional)
  const verdictLower = (valuation.verdict || "").toLowerCase()
  if (
    verdictLower === "under_review" ||
    verdictLower === "data_limited" ||
    verdictLower === "low_confidence"
  ) {
    const conf = valuation.confidence_score
    items.push({
      q: `Why is ${ticker}'s verdict Under Review?`,
      a: `Model confidence is ${conf != null ? `${conf}%` : "below threshold"}. Inputs are stale, missing, or the model fit is poor for this archetype. YieldIQ suppresses a confident verdict until data quality improves.`,
      chip: "Under Review",
    })
  }

  return items
}

export default function AnalysisFAQ({ data }: Props) {
  const items = buildFAQ(data)
  // First 3 expanded by default.
  const [open, setOpen] = useState<Set<number>>(() => new Set([0, 1, 2]))
  if (items.length === 0) return null

  const toggle = (i: number) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: items.map((it) => ({
      "@type": "Question",
      name: it.q,
      acceptedAnswer: {
        "@type": "Answer",
        text: it.a,
      },
    })),
  }

  return (
    <section
      className="bg-bg rounded-2xl border border-border p-5"
      aria-label={`Frequently asked questions about ${data.company.ticker}`}
    >
      <h2 className="text-sm font-semibold text-ink mb-3">
        Frequently asked questions
      </h2>
      <ul className="divide-y divide-border">
        {items.map((it, i) => {
          const isOpen = open.has(i)
          return (
            <li key={i} className="py-2">
              <button
                type="button"
                onClick={() => toggle(i)}
                aria-expanded={isOpen}
                className="w-full flex items-start justify-between gap-3 text-left py-1.5 group"
              >
                <span className="text-sm font-medium text-ink leading-snug">
                  {it.q}
                </span>
                <span className="flex items-center gap-2 shrink-0">
                  {it.chip && (
                    <span className="hidden sm:inline-flex items-center px-2 py-0.5 rounded-full bg-surface border border-border text-[11px] font-mono tabular-nums text-ink">
                      {it.chip}
                    </span>
                  )}
                  <svg
                    className={`w-4 h-4 text-caption transition-transform ${isOpen ? "rotate-180" : ""}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                    aria-hidden
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </span>
              </button>
              {isOpen && (
                <p className="text-sm text-body leading-relaxed mt-1 pr-6">
                  {it.a}
                </p>
              )}
            </li>
          )
        })}
      </ul>
      {/* JSON-LD for Google's FAQPage rich snippet. Kept inline so the
          markup lives next to the source of truth (the questions above).
          Next.js 15 / React 19 strip dangerouslySetInnerHTML server-side
          only when sanitizing; a JSON object is safe by construction. */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
    </section>
  )
}
