import type { Metadata } from "next"
import HelpPageShell from "../HelpPageShell"

export const metadata: Metadata = {
  title: "Portfolio Prism — YieldIQ Help",
  description:
    "How to import holdings into Portfolio Prism, what the multi-axis weighted score means, and how observations and strengths are computed.",
  alternates: { canonical: "https://yieldiq.in/help/portfolio-prism" },
}

export default function Page() {
  return (
    <HelpPageShell
      slug="portfolio-prism"
      eyebrow="04 — Workflows"
      title="Portfolio Prism"
    >
      <p>
        Portfolio Prism at <span className="font-bold">/portfolio</span>{" "}
        applies the same six-pillar Prism scoring to a basket of
        holdings rather than a single ticker. The output is a
        portfolio-level hex, a weighted composite, and a list of
        observations describing where the portfolio is concentrated
        and where it is thin.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Importing holdings
      </h2>
      <p>
        Holdings are entered manually or imported from a CSV. The
        CSV format is two columns — ticker and quantity — with an
        optional third column for average cost. The importer
        validates ticker symbols against the covered universe and
        flags any that fall outside coverage. Imported holdings live
        on your account and can be edited at any time.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        The multi-axis weighted score
      </h2>
      <p>
        Each holding contributes to the portfolio composite in
        proportion to its current market value. For every Prism
        pillar (Pulse, Quality, Moat, Safety, Growth, Value) we
        compute the value-weighted average across holdings and
        render it as a portfolio-level hex. A portfolio overweight
        in low-Quality names will show a depressed Quality axis even
        if individual holdings outside coverage are excluded from
        the average.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Observations
      </h2>
      <p>
        Observations are short, descriptive sentences computed from
        the weighted pillar scores and sector exposure. Examples:{" "}
        <em>&ldquo;Forty-two percent of the portfolio sits in
        private-sector banks&rdquo;</em>, or{" "}
        <em>&ldquo;The portfolio Safety axis is more than one
        standard deviation below the Nifty 50 benchmark.&rdquo;</em>{" "}
        Observations are descriptive only; they describe the basket
        as it currently stands, not what to do about it.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Strengths
      </h2>
      <p>
        The strengths block lists the pillars on which the portfolio
        scores in the top quartile of the covered universe. A
        portfolio with strengths in <em>Moat</em> and{" "}
        <em>Safety</em> is one whose constituents collectively score
        well on durability and balance-sheet resilience. As with
        observations, the framing is descriptive.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        What is excluded
      </h2>
      <p>
        Holdings outside the covered universe (small-caps under our
        liquidity floor, recent IPOs flagged{" "}
        <em>Under Review</em>, mutual funds, debt instruments) are
        listed separately and not factored into the weighted score.
        The portfolio header always displays the percentage of total
        value that is scored versus excluded so the score is read in
        context.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Example
      </h2>
      <p>
        A ten-holding portfolio of large-cap FMCG and IT names
        typically shows a portfolio hex with Quality and Moat well
        above the index median, Safety roughly at the index median,
        and Value below the index median — the typical signature of
        a defensively-positioned, richly-priced basket. The
        observations block surfaces the FMCG/IT concentration; the
        strengths block calls out Quality and Moat.
      </p>
    </HelpPageShell>
  )
}
