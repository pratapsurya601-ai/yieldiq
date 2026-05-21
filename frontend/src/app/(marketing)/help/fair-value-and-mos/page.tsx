import type { Metadata } from "next"
import HelpPageShell from "../HelpPageShell"

export const metadata: Metadata = {
  title: "Fair value and margin of safety — YieldIQ Help",
  description:
    "What the YieldIQ fair-value figure represents, how the margin-of-safety percentage is computed, and how to interpret each MoS band.",
  alternates: { canonical: "https://yieldiq.in/help/fair-value-and-mos" },
}

export default function Page() {
  return (
    <HelpPageShell
      slug="fair-value-and-mos"
      eyebrow="02 — Concepts"
      title="Fair value and margin of safety"
    >
      <p>
        Fair value (FV) is the per-share figure produced by the
        discounted-cash-flow engine using the base-case scenario.
        Margin of safety (MoS) is the percentage gap between fair
        value and the current market price. The two travel together:
        the FV is the model&rsquo;s central estimate of intrinsic
        worth; the MoS is the cushion the market price offers against
        that estimate being wrong.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        What fair value really is
      </h2>
      <p>
        FV is a model output, not a price target. It is the present
        value of forecast free cash flows discounted at a sector-aware
        WACC, with a terminal value computed using a sector-specific
        terminal growth rate. Inputs come from the data pipeline and
        the assumptions are disclosed in the methodology. Two
        analysts running the same DCF with different growth or
        margin assumptions will arrive at different fair values; that
        is a feature, not a bug.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        How MoS is computed
      </h2>
      <p>
        MoS is simply{" "}
        <span className="font-bold">(FV - Price) / FV</span>, expressed
        as a percentage. A FV of &#8377;1,000 against a market price
        of &#8377;700 yields a MoS of plus thirty percent. A FV of
        &#8377;1,000 against a market price of &#8377;1,300 yields a
        MoS of minus thirty percent.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Why MoS matters
      </h2>
      <p>
        Every model carries assumption error. A wider positive MoS
        means the market price is comfortably below the model&rsquo;s
        central estimate, so the answer survives a degree of input
        revision. A thin or negative MoS means the model and market
        agree, which is informative in itself but leaves no cushion.
        MoS is therefore best read as a tolerance band, not a profit
        forecast.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Reading the MoS bands
      </h2>
      <p>
        The verdict pill maps the MoS onto descriptive bands. Each
        band has a specific meaning:
      </p>
      <ul className="space-y-2 pl-5 list-disc marker:text-caption">
        <li>
          <span className="font-bold">Deep Value</span> — price below
          the bear-case FV. The market is pricing in an outcome worse
          than our most pessimistic scenario.
        </li>
        <li>
          <span className="font-bold">Below Fair Value</span> — price
          between bear and base. Meaningful MoS on the central
          estimate.
        </li>
        <li>
          <span className="font-bold">Fair Value Region</span> — price
          inside the normal dispersion of the base case. No pricing
          edge either way.
        </li>
        <li>
          <span className="font-bold">Above Fair Value</span> — price
          between base and bull. The market implies an outcome better
          than our central estimate.
        </li>
        <li>
          <span className="font-bold">Well Above Fair Value</span> —
          price above the bull-case FV. The market prices in an
          outcome better than our most optimistic scenario.
        </li>
      </ul>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Example
      </h2>
      <p>
        Suppose a mid-cap auto-ancillary trades at &#8377;420 against
        a base FV of &#8377;560, bear FV of &#8377;380, and bull FV
        of &#8377;740. The MoS on the base case is plus twenty-five
        percent — comfortably inside the bear-to-bull spread — and
        the verdict pill displays <em>Below Fair Value</em>. The
        spread is wide, so the answer is sensitive to growth and
        margin assumptions; the bear-case floor sits below the
        current price, which means the market is roughly pricing in
        a worse-than-bear outcome on the downside.
      </p>
    </HelpPageShell>
  )
}
