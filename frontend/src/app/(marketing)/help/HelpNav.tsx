import Link from "next/link"

/**
 * Side-rail navigation for the /help section. Lists all seven topic
 * pages and highlights the active one. Pure server component — no
 * client JS. Used inside each help page layout.
 *
 * Voice: descriptive. Never tells the reader what to do with stocks;
 * only describes what each page covers. SEBI-safe vocabulary only.
 */

export type HelpSlug =
  | "reading-an-analysis"
  | "fair-value-and-mos"
  | "using-the-screener"
  | "portfolio-prism"
  | "confidence-and-limits"
  | "sectors-and-cohorts"
  | "pricing-and-tiers"

export const HELP_TOPICS: {
  slug: HelpSlug
  title: string
  blurb: string
}[] = [
  {
    slug: "reading-an-analysis",
    title: "Reading a stock analysis page",
    blurb:
      "What each block on /analysis means — verdict pill, fair value, MoS, scenarios, hex, news, dividends.",
  },
  {
    slug: "fair-value-and-mos",
    title: "Fair value and margin of safety",
    blurb:
      "What the FV number really represents and how to interpret the MoS bands the verdict pill displays.",
  },
  {
    slug: "using-the-screener",
    title: "Using the screener",
    blurb:
      "Combining filters, saving queries, running presets, and reading the result columns.",
  },
  {
    slug: "portfolio-prism",
    title: "Portfolio Prism",
    blurb:
      "Importing holdings, the multi-axis weighted score, and how observations and strengths are computed.",
  },
  {
    slug: "confidence-and-limits",
    title: "Confidence and limitations",
    blurb:
      "The tri-axis confidence model, what Under Review and Low Confidence verdicts mean.",
  },
  {
    slug: "sectors-and-cohorts",
    title: "Sectors and cohorts",
    blurb:
      "Why we use sector-specific WACC and how cohort routing changes the engine for banks, REITs, and utilities.",
  },
  {
    slug: "pricing-and-tiers",
    title: "Pricing and tiers",
    blurb:
      "Feature matrix across Free, Student, Analyst, and Pro plans.",
  },
]

export default function HelpNav({ active }: { active?: HelpSlug }) {
  return (
    <nav
      aria-label="Help topics"
      className="rounded-2xl border border-border bg-bg dark:bg-surface p-4"
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-3">
        Help topics
      </p>
      <ul className="space-y-1">
        {HELP_TOPICS.map((t) => {
          const isActive = t.slug === active
          return (
            <li key={t.slug}>
              <Link
                href={`/help/${t.slug}`}
                aria-current={isActive ? "page" : undefined}
                className={
                  isActive
                    ? "block rounded-md px-3 py-2 text-sm font-semibold text-ink bg-border/40"
                    : "block rounded-md px-3 py-2 text-sm text-body hover:text-ink hover:bg-border/30 transition-colors"
                }
              >
                {t.title}
              </Link>
            </li>
          )
        })}
      </ul>
      <div className="mt-4 pt-4 border-t border-border text-xs">
        <Link
          href="/methodology"
          className="text-brand hover:underline underline-offset-4"
        >
          Full methodology &rarr;
        </Link>
      </div>
    </nav>
  )
}
