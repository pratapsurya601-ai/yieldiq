import type { Metadata } from "next"
import Link from "next/link"

/**
 * /how-it-works — public, SEO-optimised methodology page.
 *
 * Companion to the /methodology appendix: this page is the launch-day
 * marketing surface that explains the YieldIQ Three Pillars (Fair Value
 * via DCF, Moat, Sector Percentile) in plain language, with section-by-
 * section depth on each component of the score, the Piotroski bank-aware
 * mode, the YieldIQ composite, data discipline, SEBI posture, and an
 * honest list of limitations.
 *
 * Pure Server Component (no "use client") — fully SSR, zero client JS.
 * Visual conventions mirror /methodology and /about: editorial serif
 * for display, semantic color tokens (text-ink / text-body / text-caption,
 * bg-bg / bg-surface, border-border), max-w-3xl content rails, and
 * rounded-2xl card containers with a 5-unit horizontal rhythm.
 */

export function generateMetadata(): Metadata {
  const title =
    "How YieldIQ Works — DCF + Moat + Sector Percentile Methodology"
  const description =
    "How YieldIQ values every NSE stock: two-stage DCF, five-signal moat, sector-percentile bands, bank-aware Piotroski, and the composite score."
  return {
    title,
    description,
    alternates: { canonical: "https://yieldiq.in/how-it-works" },
    openGraph: {
      title,
      description,
      url: "https://yieldiq.in/how-it-works",
      siteName: "YieldIQ",
      type: "article",
      locale: "en_IN",
      images: [
        {
          url: "https://yieldiq.in/icon-512.png",
          width: 512,
          height: 512,
          alt: "YieldIQ — How it works",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: ["https://yieldiq.in/icon-512.png"],
    },
  }
}

/* ── Reusable section primitives ──────────────────────────────────── */

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

function PullQuote({ children }: { children: React.ReactNode }) {
  return (
    <blockquote className="my-6 border-l-2 border-brand pl-4 font-editorial text-lg text-ink leading-snug">
      {children}
    </blockquote>
  )
}

function PillarCard({
  badge,
  title,
  body,
}: {
  badge: string
  title: string
  body: string
}) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-2">
        {badge}
      </p>
      <h3 className="font-editorial text-xl font-semibold text-ink mb-2">
        {title}
      </h3>
      <p className="text-sm text-body leading-relaxed">{body}</p>
    </div>
  )
}

function Row({
  label,
  body,
}: {
  label: string
  body: React.ReactNode
}) {
  return (
    <li className="flex flex-col sm:flex-row sm:items-baseline sm:gap-6 py-3 border-b border-border last:border-b-0">
      <span className="text-sm font-semibold text-ink sm:w-56 shrink-0">
        {label}
      </span>
      <span className="text-sm text-body leading-relaxed">{body}</span>
    </li>
  )
}

/* ── Page ─────────────────────────────────────────────────────────── */

export default function HowItWorksPage() {
  return (
    <main className="bg-bg text-body">
      {/* ── 1. Hero — Three Pillars ─────────────────────────────── */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 pt-16 pb-12">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-4">
          How YieldIQ works
        </p>
        <h1
          className="font-editorial text-4xl sm:text-5xl font-semibold text-ink leading-tight mb-6 max-w-3xl"
          style={{ fontVariationSettings: "'opsz' 64" }}
        >
          Three pillars behind every YieldIQ verdict
        </h1>
        <p className="text-base text-body leading-relaxed max-w-2xl mb-10">
          Every stock on YieldIQ is scored against the same three
          questions: what is it actually worth, how durable is the
          business, and where does it sit against its peers? Below, in
          plain English, is exactly how we answer each one.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <PillarCard
            badge="Pillar 01"
            title="Fair Value (DCF)"
            body="Two-stage 10-year discounted cash flow with cyclical-trough handling and ADR currency awareness. Bear, base, and bull scenarios published together with a confidence interval."
          />
          <PillarCard
            badge="Pillar 02"
            title="Moat"
            body="A five-signal moat formula — margin stability, ROIC vs WACC, market share, switching costs, network effects — labelled Wide, Moderate, Narrow, or None."
          />
          <PillarCard
            badge="Pillar 03"
            title="Sector Percentile Valuation"
            body="Peer-cohort ranking against 41 to 345 same-sector NSE peers, mapped to six explicit bands from Notable discount to Notable premium."
          />
        </div>
      </section>

      {/* ── 2. The DCF in detail ────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading eyebrow="01 — Fair Value" title="The DCF, in detail" />
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            YieldIQ&rsquo;s fair-value engine is a two-stage discounted
            cash flow model: a five-year explicit projection, followed by
            a five-year fade to terminal growth. The terminal stage
            doesn&rsquo;t snap to a single number on year 11 &mdash; it
            decays smoothly, so the path the market actually walks is
            modelled rather than caricatured.
          </p>
          <p>
            <span className="text-ink font-semibold">WACC</span> is
            industry-tiered. Regulated utilities discount at roughly 9%.
            NBFCs sit 50 basis points above their non-financial peers to
            reflect the cyclicality of credit costs. Banks follow a
            separate equity-only path because the &ldquo;debt&rdquo; on a
            bank&rsquo;s balance sheet is its raw material, not its cost
            of capital.
          </p>
          <p>
            <span className="text-ink font-semibold">Terminal growth</span>{" "}
            is size-tiered. Large caps fade to 6%. Mid caps to 7%. Small
            caps to 8%. The reasoning is simple: a &#8377;20,000 Cr
            business has a lot more runway than a &#8377;5 lakh Cr one,
            and a single blanket terminal number is the failure mode that
            wrecks most public-domain DCF spreadsheets.
          </p>
          <p>
            Every valuation is published in three scenarios &mdash;
            <em> bear</em>, <em>base</em>, and <em>bull</em>. The
            scenarios flex growth, margin, and reinvestment{" "}
            <em>jointly</em>, not one input at a time. The confidence
            interval reported on the verdict reflects the spread between
            those three end-states, which is what real uncertainty looks
            like.
          </p>
        </div>

        <PullQuote>
          Reverse DCF &mdash; what FCF growth and margin must the market
          be pricing in to justify today&rsquo;s share price?
        </PullQuote>

        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            Alongside the forward model, YieldIQ runs a{" "}
            <span className="text-ink font-semibold">reverse DCF</span>{" "}
            that solves for the free cash flow growth and steady-state
            margin implied by the current share price. When the implied
            number sits well above anything the business has ever
            delivered, the model says so plainly. When it sits below
            management&rsquo;s own guidance, that&rsquo;s a setup the
            forward DCF would never tell you about on its own.
          </p>
          <p>
            <span className="text-ink font-semibold">Cyclical trough
            anchor.</span> When intrinsic value divided by price drops
            below 0.2 on a stock the classifier flags as cyclical, the
            estimate is anchored to 0.95&times; the current price instead
            of being downgraded to <em>data_limited</em>. Real cycle
            bottoms &mdash; metals, autos, oil &mdash; produce
            depressed-trailing-FCF inputs that crush a naive DCF; the
            anchor is the discipline that stops us declaring &ldquo;data
            limited&rdquo; on the very stocks where the model has the
            most to say.
          </p>
        </div>
      </section>

      {/* ── 3. The Moat formula ─────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading eyebrow="02 — Durability" title="The Moat formula" />
        <p className="text-sm text-body leading-relaxed mb-6">
          A high fair value with a thin moat is a value trap waiting to
          happen. The Moat score answers a separate question: <em>how
          durable</em> are the cash flows the DCF is discounting?
        </p>

        <ul
          className="rounded-2xl border border-border bg-surface px-5 mb-6"
          aria-label="Moat signals"
        >
          <Row
            label="Margin stability"
            body="Standard deviation of operating margin across the cycle. A high score requires the margin to hold through input-cost shocks, not just average to a flattering mean."
          />
          <Row
            label="ROIC vs WACC"
            body="The persistent spread between return on invested capital and cost of capital. We score the multi-year average; one good year doesn't prove a moat."
          />
          <Row
            label="Market share"
            body="Position within the sector cohort. Leadership matters, but so does direction; share losses to a faster competitor erode the score even if the lead survives."
          />
          <Row
            label="Switching costs"
            body="A composite of customer concentration, contract tenor, and revenue retention where disclosed. Subscription IT and enterprise pharma score highest."
          />
          <Row
            label="Network effects"
            body="A signal limited to platforms and exchanges where active-user growth itself enhances unit economics. Most stocks correctly score zero on this axis."
          />
        </ul>

        <p className="text-sm text-body leading-relaxed mb-4">
          The five signals composite to one of four labels:{" "}
          <span className="text-ink font-semibold">Wide</span>,{" "}
          <span className="text-ink font-semibold">Moderate</span>,{" "}
          <span className="text-ink font-semibold">Narrow</span>, or{" "}
          <span className="text-ink font-semibold">None</span>. A Wide
          moat lifts the YieldIQ composite by 10 points; a None
          actively penalises it.
        </p>

        <PullQuote>
          The 18-stock bellwether allowlist &mdash; HDFCBANK, HUL, NESTLE,
          TITAN, ASIANPAINT, TCS, INFY, and others &mdash; floors at
          Wide. We refuse to publish a Narrow on a 30-year compounder
          because two quarterly metrics drifted.
        </PullQuote>

        <p className="text-sm text-body leading-relaxed">
          The allowlist is small, named, version-controlled in source,
          and reviewed each year. It is not a fudge layer; it&rsquo;s a
          guard against the single most common failure mode in
          quantitative moat scoring &mdash; the model penalising
          structurally great businesses for short-term noise.
        </p>
      </section>

      {/* ── 4. Piotroski with bank-aware mode ───────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="03 — Quality"
          title="Piotroski F-Score, with a bank-aware mode"
        />
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            The classic Piotroski F-Score is nine binary fundamental
            signals: profitability, leverage, and operating efficiency.
            For non-financial businesses, YieldIQ runs it unchanged.
          </p>
          <p>
            For banks and most NBFCs, the classic formula is wrong on
            its face. Half the signals &mdash; current ratio, gross
            margin, asset turnover &mdash; are not meaningful for a
            balance-sheet business. Running the classic 9-signal on a
            bank produces a stream of false WEAK ratings even on
            HDFC Bank or Kotak.
          </p>
          <p>
            <span className="text-ink font-semibold">Bank mode</span>{" "}
            scores the four signals that <em>do</em> apply &mdash; ROA
            positive (f1), operating cash flow positive (f2), ROA
            improving year-on-year (f3), and no equity dilution (f7)
            &mdash; and rescales to the standard 0&ndash;9 range so the
            score is directly comparable to non-financials.
          </p>
        </div>

        <PullQuote>
          Most public stock screeners run the classic 9-signal Piotroski
          on every ticker, including banks. This is the single biggest
          reason their &ldquo;quality&rdquo; rankings put PSU laggards
          ahead of HDFC Bank. We don&rsquo;t.
        </PullQuote>
      </section>

      {/* ── 5. Sector Percentile Valuation ──────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="04 — Relative value"
          title="Sector Percentile Valuation"
        />
        <p className="text-sm text-body leading-relaxed mb-6">
          A DCF tells you what a stock is worth in absolute terms.
          Sector Percentile tells you where it sits inside its cohort
          &mdash; the question every investor asks second. YieldIQ ranks
          each ticker against 41 to 345 same-sector NSE peers,
          depending on sector density.
        </p>

        <ul
          className="rounded-2xl border border-border bg-surface px-5 mb-6"
          aria-label="Sector Percentile bands"
        >
          <Row
            label="Notable discount to peers"
            body="Bottom decile on the cohort's blended valuation axis. The market is paying a meaningful discount versus same-sector competitors."
          />
          <Row
            label="Below peer range"
            body="Below the cohort median but inside the normal range. Cheaper than peers, but not screaming cheap."
          />
          <Row
            label="In peer range"
            body="Inside the inter-quartile band. No relative-value edge either way on the cohort."
          />
          <Row
            label="Above peer range"
            body="Above the cohort median but inside the normal range. Pricier than peers without being extreme."
          />
          <Row
            label="Notable premium"
            body="Top decile on the cohort's blended valuation axis. The market is paying a meaningful premium versus same-sector competitors."
          />
          <Row
            label="Insufficient peer data"
            body="The cohort is too thin for a meaningful percentile (typically newly listed sectors or sub-40-stock cohorts). We say so explicitly rather than guess."
          />
        </ul>

        <p className="text-sm text-body leading-relaxed mb-4">
          Each axis on the YieldIQ Hex carries a per-axis percentile
          score: 0&ndash;100 percentile mapped to a 0&ndash;10 score via
          the linear transform <code className="font-mono text-xs text-ink">score = 10 &minus; pct/10</code>.
          That keeps each axis directly comparable across stocks even
          when the underlying distributions differ wildly.
        </p>
        <p className="text-sm text-body leading-relaxed">
          Cohort taxonomy is sector-specific. IT services run against
          IT services; private banks against private banks; PSU banks
          against PSU banks. The General catch-all cohort is used only
          when no specialised taxonomy applies, and we flag it when it
          does.
        </p>
      </section>

      {/* ── 6. The YieldIQ Score ────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading eyebrow="05 — The composite" title="The YieldIQ Score" />
        <p className="text-sm text-body leading-relaxed mb-6">
          The composite score is a single 0&ndash;100 number, decomposed
          across five axes &mdash; Quality, Safety, Value, Growth, and
          Moat &mdash; and rendered as a letter grade for quick
          scanning.
        </p>

        <ul
          className="rounded-2xl border border-border bg-surface px-5 mb-6"
          aria-label="Grade bands"
        >
          <Row label="A+ / A" body="Top-tier composite. Strong scores on all axes; no single axis below the cohort median." />
          <Row label="B+ / B" body="Solid. Strong on most axes with one or two soft spots that are usually known and disclosed." />
          <Row label="C+ / C" body="Mixed. Real strengths offset by real weaknesses; the verdict is a thinking aid, not a green light." />
          <Row label="D" body="Weak. Multiple axes below the cohort median or red-flagged on Safety. Read the report before reading the grade." />
        </ul>

        <PullQuote>
          Defence-in-depth: margin-of-safety is clamped to
          [&minus;50%, +50%] before bucketing. A single classifier gap
          should never be enough to push a stock to A+ on broken data.
        </PullQuote>

        <p className="text-sm text-body leading-relaxed">
          The clamp exists because we&rsquo;ve watched competitor
          screeners issue glowing grades on stocks where one upstream
          calculator returned a runaway MoS. The clamp ensures that the
          composite degrades gracefully when a single input is wrong,
          rather than flipping to a top grade on a single bad number.
        </p>
      </section>

      {/* ── 7. Data sources & discipline ────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="06 — Inputs"
          title="Data sources & discipline"
        />
        <ul
          className="rounded-2xl border border-border bg-surface px-5 mb-6"
          aria-label="Data sources"
        >
          <Row
            label="NSE XBRL filings"
            body="Primary source for fundamentals. Approximately eight years of structured filings, FY18 through FY25, parsed line-item by line-item with validators in front of every field."
          />
          <Row
            label="yfinance fallback"
            body="Used only for tickers and fields where NSE XBRL has gaps. Cached aggressively, gated by a process-wide circuit breaker, and validator-checked for unit-jump corruption."
          />
          <Row
            label="NSE corporate actions API"
            body="Canonical source for dividends, splits, bonuses, and bulk-deal feeds. Used for total-return and dilution checks."
          />
          <Row
            label="12 NSE sectoral indices"
            body="Bank, IT, Pharma, Auto, FMCG, Energy, Metal, Realty, Media, PSU Bank, Private Bank, and Financial Services. These are the canonical sector taxonomy used for cohort assignment."
          />
          <Row
            label="BSE filings"
            body="Used for announcements, news, and disclosures that surface on BSE first. Read-only — fundamentals come from NSE."
          />
        </ul>

        <PullQuote>
          Cache discipline: every CACHE_VERSION bump is documented in
          source with a before/after canary-diff snapshot on 50
          reference stocks. No exceptions.
        </PullQuote>
      </section>

      {/* ── 8. SEBI compliance — what we won't do ───────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="07 — Regulatory"
          title="What we won&rsquo;t do"
        />
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            YieldIQ is a research surface, not a recommendation engine.
            We are not registered with SEBI as an investment adviser or
            research analyst. The product is built so that it
            <em> cannot</em> issue advice even if we wanted it to.
          </p>
          <ul className="list-disc pl-6 space-y-2">
            <li>
              We don&rsquo;t say{" "}
              <span className="text-ink font-semibold">Buy</span>,{" "}
              <span className="text-ink font-semibold">Sell</span>,{" "}
              <span className="text-ink font-semibold">Outperform</span>,{" "}
              or <span className="text-ink font-semibold">Underperform</span>.
            </li>
            <li>We don&rsquo;t issue price targets.</li>
            <li>
              All output is a model estimate, not investment advice.
            </li>
            <li>
              A vocabulary lint runs on every PR. Any forbidden term in
              user-visible copy fails the build.
            </li>
          </ul>
          <p>
            Verdicts are descriptive, not imperative. Where data is
            insufficient we apply an explicit{" "}
            <em>Insufficient peer data</em> or <em>data_limited</em>{" "}
            label rather than guess. Consult a SEBI-registered adviser
            before making any investment decision.
          </p>
        </div>
      </section>

      {/* ── 9. Honest limitations ───────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="08 — Honesty"
          title="What YieldIQ doesn&rsquo;t do"
        />
        <ul
          className="rounded-2xl border border-border bg-surface px-5 mb-6"
          aria-label="Honest limitations"
        >
          <Row
            label="8 years of history"
            body="Not 15+. NSE&rsquo;s structured XBRL archive starts in FY18; older filings exist as PDFs but not as machine-readable line items. We use the cleanest data available rather than scraping unreliable sources for an extra five years."
          />
          <Row
            label="3,005 active NSE tickers"
            body="The full active equity universe today. We&rsquo;re expanding to a 5,000-ticker target as we add the BSE-only and SME segments, but we won&rsquo;t add a stock until the data quality clears the same bar as the rest."
          />
          <Row
            label="ADR / cross-listed names"
            body="Cross-listed ADR data quality is harder. Currency conversion, ADR-to-ordinary-share ratios, and FY mismatch all introduce noise. We flag these tickers with cross-listed (ADR / USD reporting) and data_limited where appropriate."
          />
          <Row
            label="Regulatory and M&A shocks"
            body="A DCF cannot model a sudden tariff, a competition-commission ruling, an aggressive acquirer, or a single management decision that erodes a moat overnight. The model is silent on those events; the human reading the report is not."
          />
        </ul>

        <p className="text-sm text-body leading-relaxed">
          For the long-form analyst appendix &mdash; sector-by-sector
          assumptions, the verdict-band table, and the full SEBI
          posture &mdash; see the{" "}
          <Link
            href="/methodology"
            className="text-brand hover:underline underline-offset-4"
          >
            methodology page
          </Link>
          . For pricing tiers and access, see{" "}
          <Link
            href="/pricing"
            className="text-brand hover:underline underline-offset-4"
          >
            pricing
          </Link>
          .
        </p>

        <div className="mt-10 pt-6 border-t border-border flex flex-wrap gap-4 text-sm">
          <Link
            href="/auth/signup"
            className="rounded-lg bg-brand text-white font-semibold px-4 py-2 hover:opacity-90 transition"
          >
            Start free &rarr;
          </Link>
          <Link
            href="/methodology"
            className="text-body hover:text-ink transition-colors self-center"
          >
            Long-form methodology
          </Link>
          <Link
            href="/about"
            className="text-body hover:text-ink transition-colors self-center"
          >
            About YieldIQ
          </Link>
          <Link
            href="/pricing"
            className="text-body hover:text-ink transition-colors self-center"
          >
            Pricing
          </Link>
        </div>
      </section>
    </main>
  )
}
