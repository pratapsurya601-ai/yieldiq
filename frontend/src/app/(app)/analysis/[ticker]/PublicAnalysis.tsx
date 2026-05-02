"use client"

/**
 * PublicAnalysis — the anon fallback body for /analysis/[ticker].
 *
 * Renders the Prism 6-pillar view + a summary card + inline upsell CTAs
 * in place of each gated section (AI narrative, 10-year financials,
 * peer comparison, FV-history chart, DCF chart, reverse DCF, risk).
 *
 * Why this exists: the landing page advertises "Analyse any stock free /
 * No sign-up needed" and the primary CTA lands users here. Before this
 * component, AnalysisBody's call to `getAnalysis()` 401'd for anonymous
 * visitors and the axios interceptor bounced them to /auth/login — the
 * public promise collapsed. Now anons see a genuinely useful page with
 * a clear escalation path to signup.
 *
 * Data source: /api/v1/prism/{ticker} is public and already returns the
 * hex axes, verdict, fair value, price, MoS, composite score, grade,
 * sector, and market cap — everything needed for a credible free view.
 */

import Link from "next/link"
import type { ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import api from "@/lib/api"
import { adaptPrismResponse } from "@/lib/prism"
import Prism from "@/components/prism/Prism"
import PrismSkeleton from "@/components/prism/PrismSkeleton"
import Breadcrumb, { bucketFromMarketCapCr } from "@/components/analysis/Breadcrumb"
import MetricTooltip from "@/components/analysis/MetricTooltip"
import FvConfidenceBand from "@/components/analysis/FvConfidenceBand"
import {
  formatCurrency,
  formatPct,
  formatCompanyName,
  verdictDisplayLabel,
  verdictFromMos,
} from "@/lib/utils"

/**
 * Raw Prism response shape — superset of the adapted PrismData the
 * `<Prism>` component consumes. The summary card needs several fields
 * (`price`, `fair_value`, `mos_pct`, `yieldiq_score_100`, `grade`,
 * `sector`, `market_cap_cr`) that `adaptPrismResponse` drops, so we
 * fetch the raw payload once and feed both surfaces from it.
 */
interface PrismRaw {
  ticker?: string
  company_name?: string
  sector?: string
  price?: number | null
  fair_value?: number | null
  mos_pct?: number | null
  verdict_label?: string | null
  yieldiq_score_100?: number | null
  grade?: string | null
  market_cap_cr?: number | null
  // FV-clamp consistency (NOIDATOLL +200% bug — visitor follow-up to PR #108).
  // When true, the backend has clamped fair_value/mos_pct to a plausible
  // bound; render the unclamped base-case scenario instead so the visitor
  // hero matches the logged-in EditorialHero fix and the AI summary.
  fv_clamped?: boolean
  /**
   * DCF model confidence (0–100) — mirrors ValuationOutput.confidence_score
   * on the authenticated payload. Optional here because /api/v1/prism is a
   * trimmed public payload and pre-PR backends omit it; when absent the
   * ±confidence band silently doesn't render.
   */
  confidence?: number | null
  scenarios?: {
    bear?: number | null
    base?: number | null
    bull?: number | null
    base_unclamped?: number | null
  } | null
}

const GATED_SECTIONS: Array<{ title: string; blurb: string }> = [
  {
    title: "Full DCF valuation",
    blurb:
      "10-year revenue + cash-flow forecast with bull/base/bear scenarios, terminal-value sensitivity, and a reverse-DCF to see what growth the market is already pricing in.",
  },
  {
    title: "AI analyst summary",
    blurb:
      "A plain-English read of this stock's margin of safety, moat, and red flags — generated from the underlying data, not boilerplate.",
  },
  {
    title: "10-year financial statements",
    blurb:
      "Income statement, balance sheet, and cash-flow history with quality ratios (ROE, ROCE, debt/equity) charted over time.",
  },
  {
    title: "Peer comparison",
    blurb:
      "Sector + market-cap matched peers, side-by-side on Prism axes, valuation multiples, and growth.",
  },
  {
    title: "Price + fair-value history",
    blurb:
      "See how the fair-value estimate has tracked vs. price over the last 12 months — great for spotting widening discounts.",
  },
]

export default function PublicAnalysis({ ticker }: { ticker: string }) {
  const tickerUpper = ticker.toUpperCase()

  const {
    data: raw,
    isLoading,
    isError,
  } = useQuery<PrismRaw>({
    queryKey: ["public-prism-raw", tickerUpper],
    queryFn: async () => {
      const res = await api.get(
        `/api/v1/prism/${encodeURIComponent(tickerUpper)}`,
      )
      return res.data as PrismRaw
    },
    staleTime: 60_000,
    retry: 2,
  })

  const prism = raw ? adaptPrismResponse(raw, tickerUpper) : null

  if (isLoading) {
    return (
      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        <div className="h-4 w-40 bg-subtle rounded animate-pulse mb-3" />
        <div className="h-10 w-64 bg-subtle rounded animate-pulse mb-6" />
        <div className="grid lg:grid-cols-[1fr,1fr] gap-6">
          <div className="h-72 bg-subtle rounded-2xl animate-pulse" />
          <PrismSkeleton />
        </div>
      </main>
    )
  }

  if (isError || !raw || !prism) {
    return (
      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-16 text-center">
        <h1 className="text-2xl font-display font-bold text-ink mb-2">
          Couldn&rsquo;t load analysis for {tickerUpper}
        </h1>
        <p className="text-body mb-6">
          The ticker might be mistyped, or the data service is temporarily
          unavailable. Try another stock from our search.
        </p>
        <Link
          href="/search"
          className="inline-flex items-center justify-center px-5 py-2.5 bg-brand text-white rounded-lg font-semibold hover:opacity-90 transition"
        >
          Search stocks
        </Link>
      </main>
    )
  }

  const {
    company_name,
    sector,
    market_cap_cr,
    price,
    fair_value: rawFairValue,
    mos_pct: rawMosPct,
    verdict_label,
    yieldiq_score_100,
    grade,
    fv_clamped,
    scenarios,
    confidence,
  } = raw

  // FV-clamp consistency (NOIDATOLL +200% bug — visitor view follow-up
  // to PR #108): when the backend clamped fair_value to a plausible
  // bound (FV/PX outside [0.1, 3.0] OR |MoS| ≥ 95%), the headline
  // fair_value/mos_pct on the prism payload reflect the clamp, while
  // scenarios.base_unclamped retains the meaningful base-case IV. Promote
  // base_unclamped to the headline so the visitor hero shows the same
  // numbers the AI summary + scenario grid (gated, but referenced from
  // the upsell copy) reason about. Mirrors the AnalysisBody logic added
  // in PR #108. If the unclamped base is missing or non-positive, fall
  // back to the clamped headline rather than render "—".
  const baseUnclamped = scenarios?.base_unclamped
  const useUnclamped =
    !!fv_clamped &&
    typeof baseUnclamped === "number" &&
    Number.isFinite(baseUnclamped) &&
    baseUnclamped > 0
  const fair_value = useUnclamped ? (baseUnclamped as number) : rawFairValue
  const mos_pct =
    useUnclamped && typeof price === "number" && price > 0
      ? Math.round((((baseUnclamped as number) - price) / price) * 100 * 100) / 100
      : rawMosPct

  const displayTicker = tickerUpper.replace(/\.(NS|BO)$/i, "")
  const exchange = tickerUpper.endsWith(".BO") ? "BSE" : "NSE"
  const companyDisplay = formatCompanyName(company_name ?? "", tickerUpper)
  // Single source of truth: derive verdict from MoS so the body pill,
  // the tab title (set by layout.tsx generateMetadata via verdictFromMos)
  // and the OG image all stay in lockstep. Backend `verdict_label` enum
  // is only a fallback when MoS is null/non-finite — it can drift from
  // MoS during cold-cache or stale-cache conditions and produced the
  // SBIN/TCS tab-vs-body contradiction (P0, 2026-04-30).
  const verdictText =
    typeof mos_pct === "number" && Number.isFinite(mos_pct)
      ? verdictFromMos(mos_pct)
      : verdict_label
        ? verdictDisplayLabel(verdict_label)
        : "Under Review"

  // MoS sign determines the tint of the summary pill. Positive = undervalued.
  const mosTone =
    mos_pct === null || mos_pct === undefined
      ? "neutral"
      : mos_pct >= 15
      ? "positive"
      : mos_pct <= -15
      ? "negative"
      : "neutral"

  const mosToneClasses: Record<string, string> = {
    positive: "bg-green-50 text-green-800 border-green-200",
    negative: "bg-red-50 text-red-800 border-red-200",
    neutral: "bg-amber-50 text-amber-800 border-amber-200",
  }

  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-8">
      {/* ── Breadcrumb + title ───────────────────────────────── */}
      <header className="space-y-3">
        <Breadcrumb
          exchange={exchange}
          sector={sector ?? ""}
          marketCapBucket={bucketFromMarketCapCr(market_cap_cr)}
        />
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 className="font-display text-3xl sm:text-4xl font-black text-ink tracking-tight">
            {displayTicker}
          </h1>
          <p className="text-body text-lg">{companyDisplay}</p>
        </div>
      </header>

      {/* ── Summary card + Prism ─────────────────────────────── */}
      <section className="grid lg:grid-cols-[1fr,auto] gap-6 items-start">
        <div className="bg-bg border border-border rounded-2xl p-6 shadow-sm space-y-5">
          <div
            className={`inline-flex items-center gap-2 px-3 py-1 rounded-full border text-xs font-bold uppercase tracking-wider ${mosToneClasses[mosTone]}`}
          >
            {verdictText}
          </div>

          {/* Metric labels are wrapped in <MetricTooltip> so the "?"
              icon surfaces a plain-English explainer on hover/tap.
              First-time visitors (target: retail investors without a
              fundamental-analysis background) get instant context on
              jargon like "Margin of Safety" and "YieldIQ score" without
              leaving the page. Copy lives in lib/metric_explanations.ts.
              Current price gets no tooltip — it's universally understood
              and the tight 4-up layout reads cleaner without a fourth
              icon. */}
          {/* TODO(PR-B, SEBI-compliance): render <PriceTimestamp
               as_of={as_of ?? null} /> underneath the "Current price"
               stat once the backend /api/v1/public/stock-summary
               endpoint includes `as_of` on the returned payload (the
               underlying market_data_service row already has it). */}
          <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-3">
            <Stat label="Current price" value={formatCurrency(price ?? 0, undefined, tickerUpper)} />
            <Stat
              label={<MetricTooltip metricKey="fair_value">Fair value</MetricTooltip>}
              value={fair_value ? formatCurrency(fair_value, undefined, tickerUpper) : "—"}
              // Confidence ±band beneath the headline FV — mirrors the
              // logged-in EditorialHero so the visitor view doesn't silently
              // drop a transparency cue. Renders nothing when the public
              // payload omits `confidence` or FV is unavailable.
              subtext={
                fair_value && fair_value > 0 ? (
                  <FvConfidenceBand
                    fairValue={fair_value}
                    confidence={confidence}
                  />
                ) : null
              }
            />
            <Stat
              label={<MetricTooltip metricKey="mos">Margin of safety</MetricTooltip>}
              value={
                mos_pct === null || mos_pct === undefined
                  ? "—"
                  : formatPct(mos_pct)
              }
              emphasis={mosTone === "positive"}
            />
            <Stat
              label={<MetricTooltip metricKey="yieldiq_score">YieldIQ score</MetricTooltip>}
              value={
                yieldiq_score_100 !== null && yieldiq_score_100 !== undefined
                  ? `${yieldiq_score_100}/100${grade ? ` · ${grade}` : ""}`
                  : "—"
              }
            />
          </dl>

          <p className="text-xs text-caption leading-relaxed">
            YieldIQ&rsquo;s model estimate. Not investment advice. Fair value
            is a model output based on public fundamentals and a sector-aware
            DCF, not a price target.
          </p>
        </div>

        <div className="flex flex-col items-center lg:items-end gap-2">
          <Prism data={prism} size={340} firstView />
          <Link
            href="/methodology"
            className="text-xs text-brand underline hover:opacity-80 transition"
          >
            How is this score computed? &rarr;
          </Link>
        </div>
      </section>

      {/* ── Why we're different ─────────────────────────────── */}
      <section className="bg-white border border-border rounded-2xl p-6 sm:p-7">
        <h2 className="font-display text-lg sm:text-xl font-bold text-ink mb-4">
          What makes this different
        </h2>
        <ul className="grid sm:grid-cols-3 gap-4">
          <li>
            <p className="font-semibold text-ink text-sm mb-1">Source-linked</p>
            <p className="text-sm text-body leading-relaxed">
              Every number clicks through to the filing it came from.
            </p>
          </li>
          <li>
            <p className="font-semibold text-ink text-sm mb-1">Assumptions-editable</p>
            <p className="text-sm text-body leading-relaxed">
              You can change WACC, growth, margins and re-run the DCF yourself.
            </p>
          </li>
          <li>
            <p className="font-semibold text-ink text-sm mb-1">Descriptive-only</p>
            <p className="text-sm text-body leading-relaxed">
              No SEBI-regulated buy/sell signals &mdash; a valuation layer you apply your own judgement to.
            </p>
          </li>
        </ul>
      </section>

      {/* ── Upsell ───────────────────────────────────────────── */}
      <section className="bg-gradient-to-br from-blue-50 via-white to-cyan-50 border border-blue-200 rounded-2xl p-6 sm:p-8">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div>
            <p className="text-xs font-bold text-blue-700 uppercase tracking-widest mb-1">
              Sign up (free, 1 analysis / day)
            </p>
            <h2 className="font-display text-xl sm:text-2xl font-bold text-ink">
              See the full 10-year financials, AI summary, scenario table, and editable DCF
            </h2>
          </div>
          <div className="flex flex-col sm:flex-row gap-3">
            <Link
              href={`/auth/signup?next=${encodeURIComponent(
                `/analysis/${tickerUpper}`,
              )}`}
              className="inline-flex items-center justify-center px-5 py-3 min-h-[44px] bg-brand text-white rounded-lg font-semibold hover:opacity-90 active:scale-[0.98] transition"
            >
              Create free account
            </Link>
            <Link
              href={`/auth/login?next=${encodeURIComponent(
                `/analysis/${tickerUpper}`,
              )}`}
              className="inline-flex items-center justify-center px-5 py-3 min-h-[44px] border border-brand/40 text-brand rounded-lg font-semibold hover:bg-brand-50 active:scale-[0.98] transition"
            >
              Log in
            </Link>
          </div>
        </div>

        <ul className="grid sm:grid-cols-2 gap-4">
          {GATED_SECTIONS.map((s) => (
            <li
              key={s.title}
              className="bg-white/70 backdrop-blur-sm border border-white rounded-xl p-4"
            >
              <h3 className="font-semibold text-ink mb-1">{s.title}</h3>
              <p className="text-sm text-body leading-relaxed">{s.blurb}</p>
            </li>
          ))}
        </ul>

        <p className="text-xs text-caption mt-5">
          Free tier: 5 deep analyses per day. No card required. Cancel anytime.
        </p>
      </section>
    </main>
  )
}

/* ── Helpers ─────────────────────────────────────────────── */

function Stat({
  label,
  value,
  emphasis,
  subtext,
}: {
  // Accepts a plain string OR a ReactNode so we can wrap the label in
  // MetricTooltip for jargon terms (Fair value, Margin of safety,
  // YieldIQ score) without forcing every caller to do the same.
  label: ReactNode
  value: string
  emphasis?: boolean
  // Optional sub-line beneath the value — used by the Fair value cell
  // to render the ±confidence band. Null/undefined renders nothing.
  subtext?: ReactNode
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[10px] font-bold text-caption uppercase tracking-wider">
        {label}
      </dt>
      <dd
        className={`font-mono tabular-nums text-lg sm:text-xl ${
          emphasis ? "text-green-700 font-bold" : "text-ink font-semibold"
        }`}
      >
        {value}
      </dd>
      {subtext}
    </div>
  )
}
