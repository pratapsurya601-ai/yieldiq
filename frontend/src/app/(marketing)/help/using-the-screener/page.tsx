import type { Metadata } from "next"
import HelpPageShell from "../HelpPageShell"

export const metadata: Metadata = {
  title: "Using the screener — YieldIQ Help",
  description:
    "How to combine filters in the YieldIQ screener, save queries, run presets, and read the result columns.",
  alternates: { canonical: "https://yieldiq.in/help/using-the-screener" },
}

export default function Page() {
  return (
    <HelpPageShell
      slug="using-the-screener"
      eyebrow="03 — Workflows"
      title="Using the screener"
    >
      <p>
        The screener at <span className="font-bold">/discover</span>{" "}
        lets you filter the covered universe by valuation, quality,
        and growth attributes. Filters compose with logical{" "}
        <em>AND</em> semantics — every active filter must match for a
        stock to appear in the result table.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Filter types
      </h2>
      <p>
        Filters fall into four families: valuation (MoS band, P/E,
        P/B, EV/EBITDA), quality (ROCE, ROE, margins, Piotroski
        F-score), growth (revenue and earnings CAGR), and safety
        (debt-to-equity, interest coverage, Altman-Z). Each filter
        exposes a slider or a band selector. Numeric sliders accept
        an explicit range; band selectors are mutually exclusive
        checkboxes.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Presets
      </h2>
      <p>
        Presets are curated filter combinations that we run for you.
        The Day-33 expansion ships nine of them — examples include{" "}
        <em>High ROCE</em>, <em>Quality at a Discount</em>,{" "}
        <em>Wide Moat</em>, <em>Debt-Free</em>, and{" "}
        <em>High Piotroski</em>. Each preset is a deep link with its
        filter state encoded in the URL, so sharing a preset URL
        shares the exact query.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Saving queries
      </h2>
      <p>
        Once a filter combination is composed, the{" "}
        <span className="font-bold">Save query</span> action stores
        the URL state under your account. Saved queries appear in
        the side rail of <span className="font-bold">/discover</span>{" "}
        and can be renamed or removed at any time. The Pro tier adds
        the ability to publish a saved query under a custom URL slug
        for sharing externally.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Reading the result columns
      </h2>
      <p>
        The result table renders one row per matched ticker. Columns
        from left to right: ticker and name, verdict pill, base-case
        FV, current price, MoS%, the six Prism pillar scores
        (compressed into a sparkbar), and a small confidence dot
        showing the tri-axis status. Clicking any row opens the full
        analysis page.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Sorting and pagination
      </h2>
      <p>
        Click any column header to sort by that column. The default
        order is verdict band (Deep Value first) followed by
        descending MoS. Pagination is server-side at fifty rows per
        page; the URL carries the page number so deep links into a
        result set are stable.
      </p>

      <h2 className="font-editorial text-xl font-semibold text-ink mt-6 mb-2">
        Example
      </h2>
      <p>
        To find well-capitalised mid-caps trading below base FV,
        compose: market-cap between &#8377;10,000 Cr and &#8377;50,000
        Cr, verdict in <em>Deep Value</em> or <em>Below Fair Value</em>,
        ROCE above 15 percent, debt-to-equity below 0.5. The result
        is typically a short list of fifteen-to-thirty tickers. Save
        the query, give it a name, and revisit it after the next
        quarterly cache refresh to see what has moved in or out.
      </p>
    </HelpPageShell>
  )
}
