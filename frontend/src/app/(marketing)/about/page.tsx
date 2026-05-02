import type { Metadata } from "next"
import Link from "next/link"

/**
 * /about — the Trust-Surface "who we are" page.
 *
 * Rendered as a pure Server Component (no "use client"): fully SSR,
 * zero client JS beyond what Next.js injects globally. Four sections:
 *
 *   1. Hero           — why YieldIQ exists (honest, first-person)
 *   2. How we model   — four-card summary of the analytical stack
 *   3. Data we use    — every data source with a refresh cadence
 *   4. SEBI disclosure — the long-form regulatory disclosure
 *
 * Everything on this page must be truthful: no invented awards, no
 * "trusted by thousands", no press quotes. That's the whole point of
 * the Trust Surface.
 */

export function generateMetadata(): Metadata {
  const title = "About YieldIQ — Model-based stock analysis for India"
  const description =
    "Why YieldIQ exists, how we model every NSE and BSE stock, the data sources we use, and our SEBI regulatory status."
  return {
    title,
    description,
    alternates: { canonical: "https://yieldiq.in/about" },
    openGraph: {
      title,
      description,
      url: "https://yieldiq.in/about",
      siteName: "YieldIQ",
      type: "website",
      locale: "en_IN",
      images: [
        {
          url: "https://yieldiq.in/icon-512.png",
          width: 512,
          height: 512,
          alt: "YieldIQ",
        },
      ],
    },
    twitter: {
      card: "summary",
      title,
      description,
      images: ["https://yieldiq.in/icon-512.png"],
    },
  }
}

/** Small presentational card used by the "How we model" section. */
function ModelCard({
  title,
  body,
}: {
  title: string
  body: string
}) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <h3 className="font-editorial text-lg font-semibold text-ink mb-2">
        {title}
      </h3>
      <p className="text-sm text-body leading-relaxed">{body}</p>
    </div>
  )
}

/** A single row in the "Data we use" table. */
function DataRow({
  source,
  cadence,
}: {
  source: string
  cadence: string
}) {
  return (
    <li className="flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-1 py-3 border-b border-border last:border-b-0">
      <span className="text-sm text-ink">{source}</span>
      <span className="text-xs text-caption uppercase tracking-wider">
        {cadence}
      </span>
    </li>
  )
}

export default function AboutPage() {
  return (
    <main className="bg-bg text-body">
      {/* ── Section 1 — Hero ───────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 pt-16 pb-12">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-4">
          About YieldIQ
        </p>
        <h1
          className="font-editorial text-4xl sm:text-5xl font-semibold text-ink leading-tight mb-6"
          style={{ fontVariationSettings: "'opsz' 64" }}
        >
          Why YieldIQ exists
        </h1>
        <div className="space-y-5 text-base text-body leading-relaxed">
          <p>
            Indian retail investors deserve the same quality of fundamental
            analysis that Wall Street analysts have had for decades.
          </p>
          <p>
            We built YieldIQ to model-test every stock on NSE and BSE through
            the same disciplined framework — DCF, margin of safety, moat,
            quality — that Warren Buffett and Peter Lynch made famous.
          </p>
          <p>Everything you see is free for educational use.</p>
        </div>
      </section>

      {/* ── Section 2 — How we model ───────────────────────────── */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <h2 className="font-editorial text-2xl sm:text-3xl font-semibold text-ink mb-8">
          How we model
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <ModelCard
            title="DCF fair value"
            body="Three-scenario (bear / base / bull) discounted cash flow with India-calibrated WACC derived from the 10-year G-Sec."
          />
          <ModelCard
            title="Sector-adjusted"
            body="Banks use P/BV plus ROE, IT uses revenue multiples, FMCG uses stable-growth DCF. We don't pretend every business fits one template."
          />
          <ModelCard
            title="Pulse signals"
            body="Insider trades, promoter stake changes, and analyst revisions — sourced from SEBI filings and exchange disclosures."
          />
          <ModelCard
            title="Quality score"
            body="Piotroski F-score, moat tier, and Altman Z combined into a single readable grade so you can screen at a glance."
          />
        </div>
      </section>

      {/* ── Section 3 — Data we use ────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <h2 className="font-editorial text-2xl sm:text-3xl font-semibold text-ink mb-2">
          Data we use
        </h2>
        <p className="text-sm text-caption mb-6">
          Every model is only as good as its inputs. Here's exactly where ours
          come from.
        </p>
        <ul
          className="rounded-2xl border border-border bg-surface px-5"
          aria-label="Data sources and refresh cadence"
        >
          <DataRow
            source="NSE equities master"
            cadence="Refreshed daily"
          />
          <DataRow
            source="BSE shareholding (XBRL)"
            cadence="Refreshed monthly"
          />
          <DataRow
            source="Company financials (NSE/BSE XBRL filings, with Yahoo Finance fallback cross-validated against NSE bhavcopy)"
            cadence="Refreshed weekly"
          />
          <DataRow
            source="SEBI insider filings (SAST Reg 7)"
            cadence="Refreshed daily"
          />
          <DataRow
            source="RBI 10-year G-Sec (for WACC)"
            cadence="Refreshed daily"
          />
        </ul>
      </section>

      {/* ── Section 4 — SEBI disclosure ────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <h2 className="font-editorial text-2xl sm:text-3xl font-semibold text-ink mb-6">
          Regulatory status
        </h2>
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            YieldIQ is not registered with the Securities and Exchange Board of
            India (SEBI) as an Investment Adviser (IA) or Research Analyst
            (RA).
          </p>
          <p>
            Nothing on this website constitutes investment advice, a
            recommendation to buy or sell any security, or a solicitation of
            any kind. All content is educational.
          </p>
          <p>
            Fair values are model estimates derived from publicly available
            data and disclosed assumptions. Actual outcomes may differ
            materially. Consult a SEBI-registered adviser before making
            investment decisions.
          </p>
          <p>
            Prices and data may be delayed. We make no warranties about
            accuracy or completeness.
          </p>
        </div>

        <div className="mt-10 pt-6 border-t border-border flex flex-wrap gap-4 text-sm">
          <Link
            href="/pricing"
            className="text-brand hover:underline underline-offset-4"
          >
            See pricing &rarr;
          </Link>
          <Link
            href="/terms"
            className="text-body hover:text-ink transition-colors"
          >
            Terms
          </Link>
          <Link
            href="/privacy"
            className="text-body hover:text-ink transition-colors"
          >
            Privacy
          </Link>
        </div>
      </section>
    </main>
  )
}
