import type { Metadata } from "next"
import Link from "next/link"
import { HELP_TOPICS } from "./HelpNav"

/**
 * /help — index page for the end-user help section.
 *
 * Lists the seven topic pages with one-line descriptions. Each topic
 * lives at its own URL (`/help/<slug>/page.tsx`) so Google indexes
 * them as distinct pages. Voice is descriptive, SEBI-safe: explains
 * what the app DOES, never tells the reader what to DO with stocks.
 */

export const metadata: Metadata = {
  title: "Help — using YieldIQ",
  description:
    "End-user documentation for YieldIQ — how to read an analysis page, interpret fair value and margin of safety, run the screener, and use Portfolio Prism.",
  alternates: { canonical: "https://yieldiq.in/help" },
  openGraph: {
    title: "Help — using YieldIQ",
    description:
      "End-user documentation for YieldIQ — analysis pages, fair value, the screener, Portfolio Prism, confidence indicators, and pricing tiers.",
    url: "https://yieldiq.in/help",
    siteName: "YieldIQ",
    type: "article",
    locale: "en_IN",
  },
}

export default function HelpIndexPage() {
  return (
    <main className="bg-bg text-body min-h-screen">
      <section className="max-w-3xl mx-auto px-4 sm:px-6 pt-16 pb-8">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-4">
          Help
        </p>
        <h1
          className="font-editorial text-4xl sm:text-5xl font-semibold text-ink leading-tight mb-6"
          style={{ fontVariationSettings: "'opsz' 64" }}
        >
          Using YieldIQ
        </h1>
        <p className="text-base text-body leading-relaxed">
          Short, focused pages that explain what each surface of the
          app displays and how to interpret it. For the underlying
          model assumptions, the{" "}
          <Link href="/methodology" className="text-brand hover:underline underline-offset-4">
            methodology appendix
          </Link>{" "}
          is the canonical reference.
        </p>
      </section>

      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-10 border-t border-border">
        <ul className="space-y-3">
          {HELP_TOPICS.map((t, i) => (
            <li key={t.slug}>
              <Link
                href={`/help/${t.slug}`}
                className="block rounded-2xl border border-border bg-bg dark:bg-surface p-4 hover:border-ink/40 transition-colors"
              >
                <div className="flex items-baseline gap-3 mb-1">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <h2 className="font-editorial text-lg font-semibold text-ink">
                    {t.title}
                  </h2>
                </div>
                <p className="text-sm text-body leading-relaxed">
                  {t.blurb}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-10 border-t border-border">
        <p className="text-xs text-caption leading-relaxed">
          Help pages describe how the application surfaces information.
          They are not investment advice. YieldIQ is not registered
          with SEBI as an Investment Adviser or Research Analyst. For
          regulatory posture, see{" "}
          <Link href="/methodology" className="text-brand hover:underline underline-offset-4">
            /methodology
          </Link>
          .
        </p>
      </section>
    </main>
  )
}
