import type { Metadata } from "next"
import Link from "next/link"
import HelpPageShell from "../HelpPageShell"

export const metadata: Metadata = {
  title: "Pricing and tiers — YieldIQ Help",
  description:
    "Feature matrix across YieldIQ Free, Student, Analyst, and Pro tiers, with the per-analysis pay-as-you-go option and annual plans.",
  alternates: { canonical: "https://yieldiq.in/help/pricing-and-tiers" },
}

export default function Page() {
  return (
    <HelpPageShell
      slug="pricing-and-tiers"
      eyebrow="07 — Plans"
      title="Pricing and tiers"
    >
      <p>
        YieldIQ ships four subscription tiers plus a per-analysis
        pay-as-you-go option. The canonical price card lives at{" "}
        <Link
          href="/pricing"
          className="text-brand hover:underline underline-offset-4"
        >
          /pricing
        </Link>
        ; this page summarises which features unlock at each tier
        for quick reference.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Free
      </h2>
      <p>
        Free access covers the Discover screener with all nine
        presets, the Nifty 50 / Bank / IT dashboards, the news and
        earnings calendar surfaces, and a daily allowance of basic
        analysis page views. Verdict pill, base-case FV, and the
        Prism hex are visible. Three-scenario detail, reverse DCF,
        AI summaries, and Portfolio Prism are gated.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Student / CA articleship — &#8377;199 per month
      </h2>
      <p>
        Verified students and CA articleship trainees unlock
        substantially everything on the Analyst tier — five deep
        analyses per day, three-scenario detail, AI summaries, and
        Portfolio Prism — at roughly seventy-five percent off the
        Analyst price. Verification is a one-time email exchange
        with a current ID; the tier auto-expires when the
        graduation or articleship completion date passes. Pro-tier
        exports and API access are not included.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Analyst — &#8377;799 per month
      </h2>
      <p>
        The default paid tier. Unlimited deep analyses, full
        three-scenario detail with reverse DCF, AI summaries on
        every page, multi-account portfolio import, the full
        Portfolio Prism surface with observations and strengths,
        and the Concall AI surface. Annual billing brings the
        effective price to &#8377;4,999 per year — roughly
        forty-eight percent off the monthly rate &times; 12.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Pro — &#8377;1,499 per month
      </h2>
      <p>
        Adds CSV and PDF export of analyses, screener results, and
        portfolio reports; the public REST API with a 100
        requests-per-day quota; save-and-share custom screen URLs
        under your own slug; and priority compute that bypasses the
        general queue during market hours. Built for newsletter
        writers, bloggers, and SEBI-registered advisers who need
        machine-readable output. Annual billing brings the effective
        price to &#8377;9,999 per year.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Per-analysis option — &#8377;99
      </h2>
      <p>
        A single payment of &#8377;99 grants twenty-four hours of
        full access to one ticker — every gated surface on{" "}
        <span className="font-bold">/analysis/&lt;ticker&gt;</span>,
        including the three-scenario detail, AI summary, peer
        comparison, and report card. Useful when weighing a single
        position without subscribing. Any per-analysis purchase
        rolls forward into the credit balance if you later move
        onto the Analyst tier.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Tier comparison
      </h2>
      <p>
        At a glance: Free is the screener plus daily-limited
        analyses; Student adds the Analyst feature set at the
        Student price with verification; Analyst removes the daily
        limit and unlocks Portfolio Prism plus AI summaries; Pro
        adds export, API, and priority compute on top of Analyst.
      </p>
    </HelpPageShell>
  )
}
