import type { Metadata } from "next"
import Link from "next/link"

import DisputeForm from "@/components/marketing/DisputeForm"

/**
 * /disputes — public input funnel for factual corrections.
 *
 * Sibling to /errata. /errata lists what we already fixed; /disputes
 * is where users tell us about a new issue. Triage outcomes get
 * published back to /errata so the loop is visible.
 *
 * Phase A: pure frontend. The form composes a mailto: link rather
 * than POSTing to a backend — a database table + admin triage UI is
 * Phase B (T5.8b on the roadmap).
 *
 * SEBI: this page is descriptive, not advisory. The banned-vocab guard
 * in scripts/check_sebi_words.py runs on every commit and the test
 * file disputes-page.test.tsx asserts the rendered DOM stays clean.
 */

export function generateMetadata(): Metadata {
  const title = "Disputes - Found a mistake? Tell us."
  const description =
    "Flag a factual error in a YieldIQ valuation, a model assumption you disagree with, or a copy bug. Every submission is triaged and the outcome is published to /errata."
  return {
    title,
    description,
    alternates: { canonical: "https://yieldiq.in/disputes" },
    openGraph: {
      title,
      description,
      url: "https://yieldiq.in/disputes",
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

interface CategoryCard {
  tag: string
  title: string
  description: string
  example: string
}

const CATEGORY_CARDS: readonly CategoryCard[] = [
  {
    tag: "Data",
    title: "Data correction",
    description:
      "A financial number, a sector classification, a shares-outstanding figure, a corporate action we missed — anything that disagrees with the primary filing.",
    example: 'e.g. "RELIANCE FY24 capex is wrong"',
  },
  {
    tag: "Model",
    title: "Model challenge",
    description:
      "The inputs look right but the model output diverges materially from consensus or from your own analysis. Tell us the assumption you would change and why.",
    example: 'e.g. "ITC terminal growth set at 5% looks high vs peer FMCG names - 3% fits better, here is why"',
  },
  {
    tag: "Copy",
    title: "Copy / methodology bug",
    description:
      "A caption is confusing, a label is wrong, a methodology page is out of date, a tooltip is misleading. Small wording fixes count too.",
    example: 'e.g. "The sector-medians explainer is confusing"',
  },
] as const

function CategoryCardView({ card }: { card: CategoryCard }) {
  return (
    <article className="rounded-2xl border border-border bg-surface p-6 h-full flex flex-col">
      <span className="text-[10px] font-bold uppercase tracking-wider text-brand mb-3">
        {card.tag}
      </span>
      <h3 className="font-editorial text-lg font-semibold text-ink mb-2">
        {card.title}
      </h3>
      <p className="text-sm text-body leading-relaxed mb-4 flex-1">
        {card.description}
      </p>
      <p className="text-xs text-caption italic leading-relaxed">
        {card.example}
      </p>
    </article>
  )
}

export default function DisputesPage() {
  return (
    <main className="bg-bg text-body">
      {/* Hero */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 pt-16 pb-12">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-4">
          Disputes
        </p>
        <h1
          className="font-editorial text-4xl sm:text-5xl font-semibold text-ink leading-tight mb-6"
          style={{ fontVariationSettings: "'opsz' 64" }}
        >
          Found a mistake? Tell us.
        </h1>
        <p className="text-base text-body leading-relaxed">
          YieldIQ&apos;s valuations are computed algorithmically. They contain
          errors. If you spot something wrong - a wrong financial number, a
          misclassified sector, a model output that diverges materially from
          consensus, a typo in copy - flag it here. We triage every submission
          and publish the outcome to{" "}
          <Link
            href="/errata"
            className="text-brand hover:underline underline-offset-4"
          >
            /errata
          </Link>
          .
        </p>
      </section>

      {/* Category cards */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 py-8 border-t border-border">
        <header className="mb-6 max-w-3xl">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-3">
            What you can flag
          </p>
          <h2 className="font-editorial text-2xl sm:text-3xl font-semibold text-ink">
            Three kinds of disputes we accept
          </h2>
        </header>
        <div className="grid md:grid-cols-3 gap-4">
          {CATEGORY_CARDS.map((card) => (
            <CategoryCardView key={card.tag} card={card} />
          ))}
        </div>
      </section>

      {/* Form */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <header className="mb-6">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-3">
            Submit
          </p>
          <h2 className="font-editorial text-2xl sm:text-3xl font-semibold text-ink mb-3">
            File a dispute
          </h2>
          <p className="text-sm text-body leading-relaxed">
            The submit button opens your email client with a structured message
            pre-filled. We read every email that lands at{" "}
            <a
              href="mailto:disputes@yieldiq.in"
              className="text-brand hover:underline underline-offset-4"
            >
              disputes@yieldiq.in
            </a>
            .
          </p>
        </header>
        <DisputeForm />
      </section>

      {/* Footer */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <p className="text-sm text-body leading-relaxed mb-6">
          We list contributors to corrections on{" "}
          <Link
            href="/errata"
            className="text-brand hover:underline underline-offset-4"
          >
            /errata
          </Link>{" "}
          unless you opt out. If you do not want your name published, just say
          so in the email body.
        </p>

        <div className="mt-10 pt-6 border-t border-border flex flex-wrap gap-4 text-sm">
          <Link
            href="/errata"
            className="text-body hover:text-ink transition-colors"
          >
            Past corrections
          </Link>
          <Link
            href="/methodology"
            className="text-body hover:text-ink transition-colors"
          >
            How we value stocks
          </Link>
          <Link
            href="/status"
            className="text-body hover:text-ink transition-colors"
          >
            Status
          </Link>
          <Link
            href="/help"
            className="text-body hover:text-ink transition-colors"
          >
            Help
          </Link>
        </div>
      </section>
    </main>
  )
}
