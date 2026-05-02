import type { Metadata } from "next"
import Link from "next/link"

/**
 * /methodology — the Trust-Surface methodology appendix.
 *
 * Rendered as a pure Server Component (no "use client"): fully SSR,
 * zero client JS beyond what Next.js injects globally. Seven sections:
 *
 *   1. Hero             — one-line dek framing the page
 *   2. The DCF          — inputs, three-scenario output, reverse DCF
 *   3. The 6-pillar Prism — Pulse / Quality / Moat / Safety / Growth / Value
 *   4. Verdict bands    — the six descriptive labels, including "Under Review"
 *   5. Data sources     — quotes, fundamentals, Postgres, analytical store, XBRL
 *   6. Known limitations — IPO thinness, unit-change handling, bucketing
 *   7. SEBI posture     — regulatory stance + CTA
 *
 * Voice: analyst appendix. No marketing language. Match /about visual
 * conventions (hero max-w-3xl, prose max-w-4xl for content-heavy
 * sections, editorial serif for display, semantic color tokens only).
 */

export function generateMetadata(): Metadata {
  const title = "Methodology — How YieldIQ values a stock"
  const description =
    "Open methodology for the DCF, Prism scoring, and verdict bands behind every YieldIQ analysis. Inputs, assumptions, data sources, and known limitations."
  return {
    title,
    description,
    alternates: { canonical: "https://yieldiq.in/methodology" },
    openGraph: {
      title,
      description,
      url: "https://yieldiq.in/methodology",
      siteName: "YieldIQ",
      type: "article",
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

/** Section heading used consistently across the page. */
function SectionHeading({
  eyebrow,
  title,
}: {
  eyebrow: string
  title: string
}) {
  return (
    <header className="mb-6">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-3">
        {eyebrow}
      </p>
      <h2 className="font-editorial text-2xl sm:text-3xl font-semibold text-ink">
        {title}
      </h2>
    </header>
  )
}

/** A single pillar row inside the Prism section. */
function Pillar({
  name,
  body,
}: {
  name: string
  body: string
}) {
  return (
    <div className="py-4 border-b border-border last:border-b-0">
      <h3 className="font-editorial text-lg font-semibold text-ink mb-1">
        {name}
      </h3>
      <p className="text-sm text-body leading-relaxed">{body}</p>
    </div>
  )
}

/** A single verdict-band row. */
function Band({
  label,
  body,
}: {
  label: string
  body: string
}) {
  return (
    <li className="flex flex-col sm:flex-row sm:items-baseline sm:gap-6 py-3 border-b border-border last:border-b-0">
      <span className="text-sm font-semibold text-ink sm:w-48 shrink-0">
        {label}
      </span>
      <span className="text-sm text-body leading-relaxed">{body}</span>
    </li>
  )
}

export default function MethodologyPage() {
  return (
    <main className="bg-bg text-body">
      {/* ── Section 1 — Hero ───────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 pt-16 pb-12">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-4">
          Methodology
        </p>
        <h1
          className="font-editorial text-4xl sm:text-5xl font-semibold text-ink leading-tight mb-6"
          style={{ fontVariationSettings: "'opsz' 64" }}
        >
          How YieldIQ values a stock
        </h1>
        <p className="text-base text-body leading-relaxed">
          Open methodology for the DCF, Prism scoring, and verdict bands
          behind every analysis.
        </p>
      </section>

      {/* ── Section 2 — The DCF ────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading eyebrow="01 — Valuation" title="The DCF" />
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            The core fair-value engine is a discounted-cash-flow model.
            Free cash flow is taken from the data pipeline — operating cash
            flow net of capex, cleaned for one-offs where disclosure
            permits. The discount rate is a sector-aware WACC: the Indian
            10-year G-Sec serves as the risk-free rate, sector equity-risk
            premia and betas come from{" "}
            <code className="font-mono text-xs text-ink">
              models/industry_wacc.py
            </code>
            , and the cost of debt reflects the company&rsquo;s own
            interest burden where reliable.
          </p>
          <p>
            Terminal growth is sector-specific rather than a single blanket
            number. Mature FMCG and utilities are modelled at low single
            digits; IT services and select consumer names sit higher;
            cyclicals are held close to long-run nominal GDP. The intent
            is to avoid the single worst failure mode of generic DCFs —
            one terminal assumption papered across every industry.
          </p>
          <p>
            Every valuation is published in three scenarios: <em>bear</em>,{" "}
            <em>base</em>, and <em>bull</em>. The scenarios flex growth,
            margin, and reinvestment jointly rather than one input at a
            time, so the spread reflects plausible end-states rather than
            sensitivity theatre.
          </p>
          <p>
            Alongside the forward DCF, we publish a reverse DCF that
            solves for the growth rate implied by the current market
            price. When the implied number is higher than anything the
            business has ever delivered, the reverse DCF says so plainly.
          </p>
          <p className="text-caption">
            All DCF outputs are model estimates. They are not price
            targets and nothing on this page should be read as a
            recommendation to transact.
          </p>
        </div>
      </section>

      {/* ── Section 3 — The 6-pillar Prism ─────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="02 — Scoring"
          title="The 6-pillar Prism"
        />
        <p className="text-sm text-body leading-relaxed mb-6">
          The Prism is a decomposition of business quality and valuation
          into six independently scored pillars. Each pillar is scored
          0&ndash;10, the six are composited to a /10, and the composite
          is rendered as an A&ndash;F grade on a /100 scale for quick
          scanning.
        </p>
        <div className="rounded-2xl border border-border bg-surface px-5">
          <Pillar
            name="Pulse"
            body="Short-horizon signal from recent price action and sentiment — momentum, volatility regime, and revision direction. Informative, not decisive; it sits alongside the slower-moving pillars rather than overriding them."
          />
          <Pillar
            name="Quality"
            body="Return on capital employed, return on equity, operating and net margins, and the stability of reported earnings across cycles. High scores require durability, not just a good last twelve months."
          />
          <Pillar
            name="Moat"
            body="Persistence of gross margin, evidence of pricing power through input-cost shocks, and the durability of return on capital versus peers. A high Moat score means the excess returns show up year after year, not as a one-period spike."
          />
          <Pillar
            name="Safety"
            body="Balance-sheet resilience — leverage ratios, interest coverage, and an Altman-Z-style composite adapted for Indian reporting. Financials use bank-appropriate substitutes (capital adequacy, NPA ratios) where the standard formula does not apply."
          />
          <Pillar
            name="Growth"
            body="Revenue and earnings CAGR across both 3-year and 5-year windows, blended to reward consistency over one-off spikes. Growth is reported in isolation; a high Growth score does not imply a high Value score."
          />
          <Pillar
            name="Value"
            body="The DCF margin of safety combined with sigmoid-smoothed relative multiples against sector peers. Smoothing prevents extreme multiples from collapsing the score, and the MoS weight dominates so that the label tracks the model rather than the screen."
          />
        </div>
      </section>

      {/* ── Section 4 — Verdict bands ──────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="03 — Labels"
          title="Verdict bands"
        />
        <p className="text-sm text-body leading-relaxed mb-6">
          Verdicts are descriptive, not imperative. They describe where
          the current price sits relative to the modelled fair-value
          distribution. They do not tell anyone to buy or sell.
        </p>
        <ul
          className="rounded-2xl border border-border bg-surface px-5"
          aria-label="Verdict bands"
        >
          <Band
            label="Deep Value"
            body="Price materially below the bear-case fair value. The market is pricing in an outcome worse than our most pessimistic scenario."
          />
          <Band
            label="Below Fair Value"
            body="Price below the base-case fair value but above the bear. A meaningful margin of safety on the central estimate."
          />
          <Band
            label="Fair Value Region"
            body="Price within the normal dispersion of the base case. No pricing edge either way on the modelled assumptions."
          />
          <Band
            label="Above Fair Value"
            body="Price above the base case but below the bull. The market is implying a better outcome than our central estimate."
          />
          <Band
            label="Well Above Fair Value"
            body="Price above the bull-case fair value. The market is pricing in an outcome better than our most optimistic scenario."
          />
          <Band
            label="Under Review"
            body="Insufficient data to assign a band. We apply this explicitly rather than guess — thin IPO history, unit-change ambiguity in filings, or a failed validator will all land here."
          />
        </ul>
      </section>

      {/* ── Section 5 — Data sources ───────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="04 — Inputs"
          title="Data sources"
        />
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            <span className="text-ink font-semibold">Live quotes</span>{" "}
            come from a supplementary global market data API for
            real-time and delayed prices, with a secondary feed for
            analyst estimates and corporate-event metadata. Quotes are
            cross-validated against NSE bhavcopy daily close.
          </p>
          <p>
            <span className="text-ink font-semibold">yfinance</span> is
            still used for parts of the fundamentals pipeline. It is a
            pragmatic dependency, not an ideal one. We mitigate the risk
            with an aggressive own cache, a process-wide circuit breaker
            that trips on rate-limit or error bursts, and validators that
            reject unit-jump corruption before it reaches the model.
          </p>
          <p>
            <span className="text-ink font-semibold">Managed Postgres</span>{" "}
            is the canonical store for cleaned financials, computed fair
            values, and Prism scores. Everything on the site reads
            through this layer.
          </p>
          <p>
            <span className="text-ink font-semibold">In-process analytical engine on Parquet</span>{" "}
            backs the ten-year history surfaces — price panels and the
            aggregated fundamental history used for CAGR and stability
            calculations. It is fast enough for ad-hoc analytical
            queries and immutable enough to rely on.
          </p>
          <p>
            <span className="text-ink font-semibold">NSE/BSE XBRL filings</span>{" "}
            are progressively replacing the yfinance fallback for
            fields that are reliably tagged. The rollout is
            line-item-by-line-item rather than a cutover, because any
            given filing&rsquo;s quality varies by filer.
          </p>
        </div>
      </section>

      {/* ── Section 6 — Known limitations ──────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="05 — Honesty"
          title="Known limitations"
        />
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            Recent IPOs with fewer than three years of post-listing
            financials are too thin for the Growth and Moat pillars to be
            trustworthy. These names are surfaced under{" "}
            <em>Under Review</em> rather than scored.
          </p>
          <p>
            Unit-change events in filings (lakhs versus crores, thousands
            versus millions) are handled on a best-effort basis. The
            validator suite catches the common cases; the residual risk
            is real and we disclose it.
          </p>
          <p>
            Peer selection uses a three-band market-cap bucketing —
            Large-cap above &#8377;50,000 Cr, Mid-cap between
            &#8377;10,000 Cr and &#8377;50,000 Cr, Small-cap below
            &#8377;10,000 Cr. Bucket boundaries are deliberate and
            infrequently moved, which means a stock right at a threshold
            can flip buckets on valuation days without a real change in
            its business.
          </p>
          <p>
            Sector models are shared across their sector, not bespoke to
            each ticker. A bank is modelled as a bank; an IT services
            company as IT services. The approach is intentionally
            generic: bespoke per-ticker tuning is what produces
            post-hoc-justified valuations, which is exactly what we
            want the methodology to resist.
          </p>
        </div>
      </section>

      {/* ── Section 7 — SEBI posture + CTA ─────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="06 — Regulatory"
          title="SEBI posture"
        />
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            YieldIQ is not registered with the Securities and Exchange
            Board of India as an Investment Adviser or Research Analyst.
            Nothing on the site is investment advice, a recommendation,
            or a solicitation.
          </p>
          <p>
            Verdicts are descriptive rather than imperative. Where data
            quality is insufficient, we apply an explicit{" "}
            <em>Under Review</em> label instead of forcing a call.
            Fair-value outputs are model estimates derived from publicly
            available inputs and disclosed assumptions; actual outcomes
            may differ materially.
          </p>
          <p>
            Do your own research. Consult a SEBI-registered adviser
            before making investment decisions.
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
            href="/about"
            className="text-body hover:text-ink transition-colors"
          >
            About YieldIQ
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
