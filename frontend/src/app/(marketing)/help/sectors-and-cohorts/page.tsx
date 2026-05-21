import type { Metadata } from "next"
import HelpPageShell from "../HelpPageShell"

export const metadata: Metadata = {
  title: "Sectors and cohorts — YieldIQ Help",
  description:
    "Why YieldIQ uses sector-specific WACC, how cohort routing changes the engine for banks, REITs, and regulated utilities, and what sector-aware modelling means in practice.",
  alternates: { canonical: "https://yieldiq.in/help/sectors-and-cohorts" },
}

export default function Page() {
  return (
    <HelpPageShell
      slug="sectors-and-cohorts"
      eyebrow="06 — Modelling"
      title="Sectors and cohorts"
    >
      <p>
        A single DCF template applied across all industries is the
        most common failure mode in retail valuation tools. YieldIQ
        uses sector-aware inputs and a cohort router so that a bank,
        a REIT, an IT services company, and a regulated utility each
        get a model that fits their economics.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Sector-specific WACC
      </h2>
      <p>
        The discount rate in the DCF is a weighted average cost of
        capital that varies by sector. The risk-free leg is the
        Indian 10-year G-Sec; the equity-risk premium and beta come
        from sector tables in{" "}
        <span className="font-bold">models/industry_wacc.py</span>;
        the cost of debt reflects the company&rsquo;s own interest
        burden where reliable. A utility with stable cash flows
        carries a lower WACC than a cyclical commodity producer,
        which is what the published numbers reflect.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Cohort routing
      </h2>
      <p>
        Cohort routing decides which valuation engine runs for a
        given ticker. The router inspects the company&rsquo;s
        primary business, regulatory status, and balance-sheet shape
        before selecting an engine. The major cohorts are:
      </p>
      <ul className="space-y-2 pl-5 list-disc marker:text-caption">
        <li>
          <span className="font-bold">Banks and NBFCs</span> —
          residual-income / dividend-discount with capital-adequacy
          and credit-cost inputs rather than free-cash-flow DCF.
        </li>
        <li>
          <span className="font-bold">REITs and InvITs</span> —
          distributable cash flow with explicit treatment of asset
          maturity and the regulated payout floor.
        </li>
        <li>
          <span className="font-bold">Regulated utilities</span> —
          allowed-RoE-driven cash flow with regulatory true-up
          assumptions and tariff-period sensitivities.
        </li>
        <li>
          <span className="font-bold">Cyclicals</span> — normalised
          earnings averaged across a sector-specific cycle length
          (steel and cement, for example, are normalised over
          longer windows than auto-ancillaries).
        </li>
        <li>
          <span className="font-bold">Generic</span> — standard free
          cash flow to firm with sector-aware terminal growth, used
          for IT services, consumer, pharma, and industrials.
        </li>
      </ul>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Sector-specific terminal growth
      </h2>
      <p>
        Terminal growth is set per sector rather than as a single
        blanket figure. Mature FMCG and utilities are modelled at
        low single digits; IT services and select consumer names
        sit higher; cyclicals are pinned close to long-run nominal
        GDP. The intent is to avoid the single largest source of
        DCF error in retail tools — one terminal assumption pasted
        across every industry.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Peer cohorts on /compare
      </h2>
      <p>
        On the comparison surface the peer cohort is the set of
        tickers that share the same sector and market-cap bucket.
        The Day-80 transparency captions display the cohort
        definition so the reader can see exactly which peer set the
        comparison is drawn from. A ticker right at the edge of a
        cap bucket may sit alongside a different peer set after a
        large move.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Example
      </h2>
      <p>
        A private-sector bank is routed through the bank engine,
        which means capital adequacy and credit-cost trajectory
        replace free-cash-flow as the primary inputs. The Prism
        Safety pillar substitutes leverage and interest-coverage
        with capital-adequacy and NPA ratios. The verdict pill and
        FV are still rendered in the same place on the page, but
        the underlying computation is materially different from
        what a generic DCF would produce.
      </p>
    </HelpPageShell>
  )
}
