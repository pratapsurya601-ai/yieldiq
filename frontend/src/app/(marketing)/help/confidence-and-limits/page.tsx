import type { Metadata } from "next"
import HelpPageShell from "../HelpPageShell"

export const metadata: Metadata = {
  title: "Confidence and limitations — YieldIQ Help",
  description:
    "The tri-axis confidence model (data quality, model confidence, valuation stability), what Under Review and Low Confidence mean, and when to trust the number.",
  alternates: { canonical: "https://yieldiq.in/help/confidence-and-limits" },
}

export default function Page() {
  return (
    <HelpPageShell
      slug="confidence-and-limits"
      eyebrow="05 — Trust"
      title="Confidence and limitations"
    >
      <p>
        Every fair-value figure on YieldIQ carries three confidence
        axes alongside it: <span className="font-bold">data quality</span>
        , <span className="font-bold">model confidence</span>, and{" "}
        <span className="font-bold">valuation stability</span>. The
        axes determine which verdict label the pill renders. When any
        axis is red, the verdict is gated to a non-committal label
        rather than forcing a confident-looking band that the inputs
        cannot defend.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Data quality
      </h2>
      <p>
        The data-quality axis tracks how complete and recent the
        underlying financials are. It turns amber when one or more
        required line items came from a fallback source, and red when
        a validator rejected an input — a unit-jump corruption, a
        stale annual filing past its tolerance window, or a failed
        cross-check against bhavcopy close.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Model confidence
      </h2>
      <p>
        The model-confidence axis tracks how well the chosen engine
        fits the business. A regulated utility scored through the
        utility engine carries higher model confidence than a
        new-economy listing routed through the generic engine because
        thin growth history forces the engine to lean on assumptions.
        Cohort routing (see{" "}
        <a
          href="/help/sectors-and-cohorts"
          className="text-brand hover:underline underline-offset-4"
        >
          sectors and cohorts
        </a>
        ) is the main driver of this axis.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Valuation stability
      </h2>
      <p>
        The valuation-stability axis measures how much the published
        FV has moved across the last several cache refreshes. A FV
        that has drifted within plus/minus five percent is stable; a
        FV that has swung twenty percent on each refresh is unstable
        and the axis turns amber. Instability is usually a symptom of
        thin or volatile inputs rather than a model defect.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Under Review
      </h2>
      <p>
        When the data-quality axis is red, the verdict pill renders{" "}
        <em>Under Review</em>. This is an explicit refusal to assign
        a band rather than a fallback guess. Recent IPOs with fewer
        than three years of post-listing financials, tickers with a
        failed validator on a required input, and companies in the
        middle of a unit-change correction will land here. The page
        still renders the partial Prism pillars where they are
        defensible.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Low Confidence
      </h2>
      <p>
        When the model-confidence or valuation-stability axes are
        amber but data quality is green, the verdict pill renders{" "}
        <em>Low Confidence</em> alongside its band label. The band
        is still computed and displayed; the label simply flags that
        the answer rests on a thinner foundation than usual.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        When to lean on the number
      </h2>
      <p>
        The FV is most trustworthy when all three axes are green, the
        company sits in a well-modelled cohort (large-cap IT services,
        private-sector banks, mature FMCG), and the bear-to-bull
        spread is tight. The same FV is least trustworthy when an
        axis is amber, the cohort is thin (recent IPOs, complex
        holdcos), or the spread is wide. Consider the axes before
        the band.
      </p>
    </HelpPageShell>
  )
}
