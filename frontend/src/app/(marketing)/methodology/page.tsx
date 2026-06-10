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

/**
 * A single sector-engine card. Each engine documents:
 *   - title + one-line tagline
 *   - routes: which sectors / example tickers feed in
 *   - rationale: why DCF alone is inadequate for this sector
 *   - inputs: 3-5 key drivers used by the engine
 */
function Engine({
  name,
  tagline,
  routes,
  rationale,
  inputs,
}: {
  name: string
  tagline: string
  routes: string
  rationale: string
  inputs: readonly string[]
}) {
  return (
    <div className="py-5 border-b border-border last:border-b-0">
      <h3 className="font-editorial text-lg font-semibold text-ink mb-1">
        {name}
      </h3>
      <p className="text-xs text-caption mb-3">{tagline}</p>
      <dl className="grid gap-y-2 text-sm leading-relaxed">
        <div className="flex flex-col sm:flex-row sm:gap-3">
          <dt className="text-ink font-semibold sm:w-28 shrink-0">Routes</dt>
          <dd className="text-body">{routes}</dd>
        </div>
        <div className="flex flex-col sm:flex-row sm:gap-3">
          <dt className="text-ink font-semibold sm:w-28 shrink-0">
            Why DCF alone is inadequate
          </dt>
          <dd className="text-body">{rationale}</dd>
        </div>
        <div className="flex flex-col sm:flex-row sm:gap-3">
          <dt className="text-ink font-semibold sm:w-28 shrink-0">
            Key inputs
          </dt>
          <dd className="text-body">
            <ul className="space-y-1 pl-5 list-disc marker:text-caption">
              {inputs.map((input) => (
                <li key={input}>{input}</li>
              ))}
            </ul>
          </dd>
        </div>
      </dl>
    </div>
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
          <p className="text-caption">{/* sebi-allow: should, recommendation */}
            All DCF outputs are model estimates. They are not price
            targets and nothing on this page should be read as a
            recommendation to transact.
          </p>
        </div>
      </section>

      {/* ── Section 2.5 — Specialized models by sector ─────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="02 — Routing"
          title="When DCF isn't enough — specialized models by sector"
        />
        <p className="text-sm text-body leading-relaxed mb-6">
          A single DCF cannot value every business shape. A bank does
          not have free cash flow in the normal sense; a REIT is a
          pass-through; a regulated utility earns a tariff-capped
          return that compounds in DCF math into something the
          regulator has never permitted. YieldIQ routes each ticker
          to a sector-appropriate engine, then anchors the answer
          against peer multiples and a reverse-DCF cross-check.
        </p>
        <div className="rounded-2xl border border-border bg-surface px-4">
          <Engine
            name="Multiples-based fair value"
            tagline="Peer-relative PE / PB / EV-EBITDA — runs on every ticker as a parallel signal to the DCF."
            routes="All tickers, including those already routed to a specialized engine."
            rationale="DCF outputs drift when terminal-growth and WACC assumptions move by a hundred basis points. Peer-relative multiples anchor the DCF against the price that comparable businesses actually trade at, surfacing disagreements rather than hiding them."
            inputs={[
              "Sector-cohort PE / PB / EV-EBITDA percentiles",
              "Bucketed peer set (large / mid / small-cap)",
              "Cohort median + sigmoid-smoothed dispersion",
              "Subject ticker's own three-year ratio history",
            ]}
          />
          <Engine
            name="Bank residual-income"
            tagline="P/BV times adjusted book value with a residual-income overlay."
            routes="Private and PSU banks (HDFCBANK, ICICIBANK, SBIN), large NBFCs (BAJFINANCE), life insurers (HDFCLIFE)."
            rationale="Banks do not produce free cash flow in the sense an industrial does. Their economic engine is net interest margin earned on book equity, not operating cash flow net of capex. A DCF on a bank treats deposits as a financing item that funds operations, which inverts the actual business model. Book value plus the spread between return on equity and cost of equity is the textbook frame."
            inputs={[
              "Return on equity, current and three-year trailing",
              "Cost of equity from a bank-specific WACC sheet",
              "Net interest margin and CASA mix",
              "Provision coverage ratio and gross NPA trajectory",
              "Adjusted book value (book equity net of intangibles + visible stress)",
            ]}
          />
          <Engine
            name="REIT net-asset-value with DPU yield gap"
            tagline="Underlying property NAV plus distribution-per-unit yield versus the 10-year G-Sec."
            routes="Listed REITs and InvITs (EMBASSY, MINDSPACE, BROOKFIELD, IRBINVIT)."
            rationale="A REIT is a regulated pass-through that distributes 90 percent of its cash flow. A pure DCF on the distribution stream misses the property-level appreciation that drives unit value, and a pure NAV ignores the income premium. Both halves matter, weighted to the way the unit actually clears in the market."
            inputs={[
              "Underlying property NAV from the sponsor's filings",
              "Trailing-twelve-month DPU",
              "10-year G-Sec yield as the risk-free anchor",
              "Sector-cohort yield spread (REIT DPU yield minus G-Sec)",
              "Occupancy and lease-roll schedule for the next three years",
            ]}
          />
          <Engine
            name="Regulated utility — RAB times allowed ROE"
            tagline="Regulated Asset Base multiplied by the regulator's allowed return on equity."
            routes="Power transmission and generation utilities (POWERGRID, NTPC, transmission DISCOMs)."
            rationale="A regulated utility earns a tariff-capped return on a defined asset base. The regulator (CERC, SERCs) sets the allowed return on equity in five-year tariff orders. A DCF that compounds historical FCF growth ignores the cap and produces a number the regulator has never permitted. RAB times allowed-ROE is the frame the company itself reports against."
            inputs={[
              "Regulated Asset Base from the latest tariff order",
              "Allowed return on equity in the current control period",
              "Capex run-rate that flows into next-period RAB",
              "Under-recoveries and regulatory assets on the balance sheet",
              "Tariff-petition outcomes from prior cycles",
            ]}
          />
          <Engine
            name="Platform / recent-IPO sector relative"
            tagline="Sector-relative valuation for businesses with under 36 months of public data."
            routes="Recent IPOs and platform businesses (ZOMATO, NYKAA, PAYTM, POLICYBZR, MANKIND in its first year)."
            rationale="A DCF needs at least three to five years of revenue, margin, and reinvestment history to calibrate baseline assumptions. A recently-listed platform has neither the history nor a stable cohort to lean on. Forcing a DCF here produces a spuriously precise number from noisy inputs. Sector-relative valuation flags the price as a band rather than a point and waits for the data to mature."
            inputs={[
              "Closest comparable cohort (Indian + global platform peers)",
              "Trailing GMV / contribution-margin trajectory",
              "Cohort EV / sales and EV / contribution-margin multiples",
              "Months of public reporting (gates the model out under 6 months)",
            ]}
          />
          <Engine
            name="Tier-2 cohort"
            tagline="Cohort-relative valuation for mid-caps where direct DCF inputs are noisy."
            routes="Hand-curated tier-2 list across cyclicals, capital goods, and specialty chemicals."
            rationale="Small and mid-cap DCFs are dominated by single-year cash-flow swings — one capex year or one inventory cycle can flip the answer. Cohort-relative valuation smooths these inputs by anchoring against five to ten name-level peers in the same sub-sector. The output is wider but more honest about its own uncertainty."
            inputs={[
              "Sub-sector cohort of 5-10 hand-curated peers",
              "Median PE, PB, EV-EBITDA across the cohort",
              "Subject's three-year normalized margin (median-of-window)",
              "Confidence haircut applied when cohort dispersion is wide",
            ]}
          />
          <Engine
            name="Reverse DCF"
            tagline="Back-solves the growth rate the current market price already implies."
            routes="All tickers — surfaces alongside the forward DCF as a transparency signal."
            rationale="The forward DCF asks 'what is this worth?' The reverse DCF asks 'what does buying at the current price assume?' When the implied growth rate is higher than anything the business has delivered, the reverse DCF says so plainly. It reframes valuation as a check on market-implied expectations rather than a single answer."
            inputs={[
              "Current market price",
              "Last reported FCF (or normalized FCF for cyclicals)",
              "Discount rate (same sector WACC as the forward DCF)",
              "Terminal growth assumption (same as the forward DCF)",
              "Implied growth rate solved over the explicit forecast window",
            ]}
          />
          <Engine
            name="Story DCF / Day-89 backtest"
            tagline="Historical revenue and margin path plus what-if scenarios for the YIQ50 backtest set."
            routes="YIQ50 backtest universe — the harness that produced the public Day-89 results."
            rationale="A single headline DCF hides which assumption is doing the work. The story DCF lets a user flex revenue growth, margin trajectory, or reinvestment rate one at a time and watch the fair value move. The Day-89 backtest panel shows how each story would have played out historically, so users can challenge the central case with their own narrative."
            inputs={[
              "Historical revenue and margin path (10-year window)",
              "User-flexed growth, margin, and reinvestment scenarios",
              "Sector-specific terminal growth ceiling",
              "Backtest accuracy versus realized prices on the YIQ50 set",
            ]}
          />
          <Engine
            name="Composite intrinsic value"
            tagline="Weighted blend of DCF, multiples-based fair value, and Wall Street consensus."
            routes="All tickers — surfaces as a parallel column next to the DCF-only fair value."
            rationale="A pure DCF can run high relative to peer multiples and analyst consensus on names where terminal-growth assumptions matter most — large private banks and high-quality compounders. The composite blends three independent signals so no single methodology can dominate the headline number. Each input remains visible so users can see where the disagreement sits."
            inputs={[
              "Forward DCF fair value with three-scenario distribution",
              "Multiples-based fair value (sector-cohort anchored)",
              "Wall Street consensus target where coverage exists",
              "Sector-specific weighting between the three inputs",
            ]}
          />
          <Engine
            name="Holdco sum-of-the-parts"
            tagline="SOTP for pure holding companies whose value is a basket of stakes — currently shipping as a DCF-only stop-gap."
            routes="Pure holdcos (BAJAJHLDNG and similar). Subsidiaries with operating businesses route to their own sector engine."
            rationale="A pure holding company's value is the sum of its stakes in listed and unlisted subsidiaries, not a discounted-cash-flow on its own thin parent-entity cash flows. DCF on the parent entity misses the subsidiary value entirely. A proper SOTP marks each stake to its underlying fair value and applies a holdco discount for liquidity, control, and tax frictions."
            inputs={[
              "Market value of each listed-subsidiary stake",
              "DCF fair value of each unlisted-subsidiary stake",
              "Holdco discount (typically 20-40 percent in the Indian market)",
              "Parent-entity net debt and treasury holdings",
            ]}
          />
        </div>

        {/* Honest caveats sub-section */}
        <div className="mt-10 pt-8 border-t border-border">
          <h3 className="font-editorial text-xl font-semibold text-ink mb-4">
            Honest caveats
          </h3>
          <div className="space-y-4 text-sm text-body leading-relaxed">
            <p>
              <span className="text-ink font-semibold">
                Composite IV closes a real DCF-only gap.
              </span>{" "}
              On HDFCBANK, the DCF-only fair value ran materially
              above the peer-multiples and AlphaSpread numbers. The
              composite engine blends DCF, multiples, and consensus
              so that bias collapses into a band the three methods
              actually agree on. We publish both columns side by side
              rather than hiding the DCF-only output.
            </p>
            <p>
              <span className="text-ink font-semibold">
                Holdco SOTP is a stop-gap.
              </span>{" "}
              The current holdco route is a DCF-only fallback that
              under-counts subsidiary value. A real
              sum-of-the-parts engine is in the roadmap; until it
              ships, BAJAJHLDNG and similar pure holdcos carry an
              under-review caveat on the analysis page.
            </p>
            <p>
              <span className="text-ink font-semibold">
                Three sector engines are still on the roadmap.
              </span>{" "}
              Pharma pipeline-adjusted DCF (probability-weighted
              molecule cash flows), Insurance embedded-value plus
              value-of-new-business, and Telecom ARPU-driven models
              are not yet shipped. Until they are, the relevant
              tickers route through the general DCF with a
              sector-cohort multiples cross-check, and any large
              gap between the two surfaces as an under-review band.
            </p>
          </div>
        </div>
      </section>

      {/* ── Section 3 — The 6-pillar Prism ─────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="03 — Scoring"
          title="The 6-pillar Prism"
        />
        <p className="text-sm text-body leading-relaxed mb-6">
          The Prism is a decomposition of business quality and valuation
          into six independently scored pillars. Each pillar is scored
          0&ndash;10, the six are composited to a /10, and the composite
          is rendered as an A&ndash;F grade on a /100 scale for quick
          scanning.
        </p>
        <div className="rounded-2xl border border-border bg-surface px-4">
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
          eyebrow="04 — Labels"
          title="Verdict bands"
        />
        <p className="text-sm text-body leading-relaxed mb-6">{/* sebi-allow: buy, sell */}
          Verdicts are descriptive, not imperative. They describe where
          the current price sits relative to the modelled fair-value
          distribution. They do not tell anyone to buy or sell.
        </p>
        <ul
          className="rounded-2xl border border-border bg-surface px-4"
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
          eyebrow="05 — Inputs"
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
          eyebrow="06 — Honesty"
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

      {/* ── Section 6.5 — AI summaries disclosure ──────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="07 — AI"
          title="AI summaries — full disclosure"
        />
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            The single-paragraph summary at the top of each analysis
            page is generated by a large language model. The numbers
            below the summary are authoritative. The AI is summarising,
            not deciding. If they ever disagree, the numbers are right.
          </p>
          <ul className="space-y-2 pl-5 list-disc marker:text-caption">
            <li>
              <span className="text-ink font-semibold">Model:</span>{" "}
              <code className="font-mono text-xs text-ink">
                Groq llama-3.3-70b-versatile
              </code>
            </li>
            <li>
              <span className="text-ink font-semibold">Temperature:</span>{" "}
              0.3 (low &mdash; deterministic-leaning)
            </li>
            <li>
              <span className="text-ink font-semibold">Inputs:</span>{" "}
              ticker, fair_value, current_price, MoS%, verdict, score,
              Piotroski/9, moat grade, revenue CAGR, key red flags
            </li>
            <li>
              <span className="text-ink font-semibold">System prompt:</span>{" "}
              &ldquo;You are a SEBI-compliant analyst summarizing model
              output. Use &#8377; for all values. No buy/sell/hold
              language. State the verdict band, the gap to fair value,
              and 2&ndash;3 driver metrics. Max 3 sentences.&rdquo;
            </li>
            <li>
              <span className="text-ink font-semibold">Regenerated:</span>{" "}
              on each cache miss (typically every 24h or after a data
              change)
            </li>
          </ul>
        </div>
      </section>

      {/* ── Section 7 — SEBI posture + CTA ─────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="08 — Regulatory"
          title="SEBI posture"
        />
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>{/* sebi-allow: recommendation */}
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

        <div className="mt-8 pt-6 border-t border-border flex flex-wrap gap-4 text-sm">
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
