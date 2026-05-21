import type { Metadata } from "next"
import HelpPageShell from "../HelpPageShell"

export const metadata: Metadata = {
  title: "Reading a stock analysis page — YieldIQ Help",
  description:
    "What every block on the YieldIQ analysis page displays — verdict pill, fair value, MoS, scenarios, Prism hex, news, and dividend history.",
  alternates: { canonical: "https://yieldiq.in/help/reading-an-analysis" },
}

export default function Page() {
  return (
    <HelpPageShell
      slug="reading-an-analysis"
      eyebrow="01 — Surfaces"
      title="Reading a stock analysis page"
    >
      <p>
        The <span className="font-bold">/analysis/&lt;ticker&gt;</span>{" "}
        page is the canonical surface for a single stock. It is laid
        out top-to-bottom in the same order on every ticker so the
        eye learns where each block lives. This page walks through
        each block in order.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Header — verdict pill and price
      </h2>
      <p>
        The header carries the ticker, current price, and the{" "}
        <span className="font-bold">verdict pill</span> — a single
        descriptive label such as <em>Deep Value</em>,{" "}
        <em>Below Fair Value</em>, <em>Fair Value Region</em>,{" "}
        <em>Above Fair Value</em>, <em>Well Above Fair Value</em>, or{" "}
        <em>Under Review</em>. The pill describes where the current
        price sits relative to the modelled fair-value distribution;
        it is not imperative.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Fair value and margin of safety
      </h2>
      <p>
        Below the header you see the base-case fair value as a single
        rupee figure, the current price, and the margin-of-safety (MoS)
        percentage between the two. A positive MoS means the model
        places fair value above the market price; a negative MoS means
        the opposite.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Three scenarios
      </h2>
      <p>
        Every valuation is published in three jointly flexed scenarios
        — <em>bear</em>, <em>base</em>, and <em>bull</em>. The chart
        renders all three so the spread is visible. A wide spread
        means the answer is sensitive to assumptions; a tight spread
        means the model converges across plausible end-states.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Confidence indicators
      </h2>
      <p>
        Three small badges sit alongside the verdict — data quality,
        model confidence, and valuation stability. When any axis is
        red the verdict pill is gated to <em>Under Review</em> or{" "}
        <em>Low Confidence</em> rather than rendering a band that
        cannot be defended. See{" "}
        <a
          href="/help/confidence-and-limits"
          className="text-brand hover:underline underline-offset-4"
        >
          confidence and limitations
        </a>{" "}
        for the full tri-axis explanation.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Prism hex
      </h2>
      <p>
        The six-axis radar (Pulse, Quality, Moat, Safety, Growth,
        Value) is the visual summary of the 6-pillar Prism score. A
        balanced hex means the business scores evenly across pillars;
        an asymmetric hex highlights where the business scores well
        and where it scores thinly.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        News and dividends
      </h2>
      <p>
        Below the model output the page lists recent filings and
        tier-tagged news (Day-79 sourcing), followed by the dividend
        history — payout streak, sustainability classifier, and yield
        on cost. Each row links to source filings where available.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Example
      </h2>
      <p>
        On a typical large-cap IT services name you might see a
        verdict of <em>Fair Value Region</em>, MoS within plus/minus
        five percent, a tight bear-to-bull spread, all three confidence
        axes green, and a balanced Prism hex with Quality and Moat
        scoring above 7/10. That combination describes a richly priced
        but well-understood business — the model is confident in the
        number, the number is close to the market, and the spread is
        narrow.
      </p>
    </HelpPageShell>
  )
}
