import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"
import {
  EDUCATIONAL_TOPICS,
  getAllTopicSlugs,
  resolveTopic,
  type EducationalTopic,
} from "@/lib/educational-content"

/**
 * /learn/<topic> — per-metric long-form explainer page.
 *
 * Same content model as the MetricExplainer modal, but rendered as a
 * full SEO page with JSON-LD, sitemap inclusion, and a "Related topics"
 * footer for internal-link velocity. Generated statically at build time
 * — every slug in EDUCATIONAL_TOPICS pre-renders to a static HTML file.
 *
 * Server Component, fully SSR. No client JS.
 */

interface PageProps {
  // Next.js 16 streams params as a Promise — await before reading.
  params: Promise<{ topic: string }>
}

// Pre-render every topic at build time so /learn/<slug> is a static file.
export function generateStaticParams() {
  return getAllTopicSlugs().map((slug) => ({ topic: slug }))
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { topic } = await params
  const entry = resolveTopic(topic)
  if (!entry) {
    return {
      title: "Topic not found — YieldIQ Learn",
      robots: { index: false, follow: false },
    }
  }
  const title = `${entry.title} — Definition, formula, ranges | YieldIQ Learn`
  const description = entry.subtitle
  const url = `https://yieldiq.in/learn/${entry.slug}`
  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: {
      title,
      description,
      url,
      siteName: "YieldIQ",
      type: "article",
      locale: "en_IN",
      images: [
        {
          url: "https://yieldiq.in/icon-512.png",
          width: 512,
          height: 512,
          alt: "YieldIQ Learn",
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

/**
 * Build a DefinedTerm + Article JSON-LD block so Google can surface
 * the entry as a definition card.
 */
function topicJsonLd(entry: EducationalTopic): string {
  const payload = {
    "@context": "https://schema.org",
    "@type": "DefinedTerm",
    name: entry.title,
    description: entry.definition,
    inDefinedTermSet: {
      "@type": "DefinedTermSet",
      name: "YieldIQ Learn — Finance Glossary",
      url: "https://yieldiq.in/learn",
    },
    url: `https://yieldiq.in/learn/${entry.slug}`,
    termCode: entry.slug,
  }
  return JSON.stringify(payload)
}

export default async function LearnTopicPage({ params }: PageProps) {
  const { topic } = await params
  const entry = resolveTopic(topic)
  if (!entry) notFound()

  const related = entry.relatedTopics
    .map((slug) => EDUCATIONAL_TOPICS[slug])
    .filter((t): t is EducationalTopic => Boolean(t))

  return (
    <main className="bg-bg text-body">
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: topicJsonLd(entry) }}
      />

      {/* Breadcrumb */}
      <nav
        aria-label="Breadcrumb"
        className="max-w-3xl mx-auto px-4 sm:px-6 pt-8"
      >
        <ol className="flex items-center gap-1.5 text-[12px] text-caption">
          <li>
            <Link href="/" className="hover:text-ink hover:underline">
              Home
            </Link>
          </li>
          <li aria-hidden="true">/</li>
          <li>
            <Link href="/learn" className="hover:text-ink hover:underline">
              Learn
            </Link>
          </li>
          <li aria-hidden="true">/</li>
          <li className="text-ink font-medium" aria-current="page">
            {entry.title}
          </li>
        </ol>
      </nav>

      {/* Hero */}
      <header className="max-w-3xl mx-auto px-4 sm:px-6 pt-6 pb-10">
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <span className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption">
            {entry.category}
          </span>
          <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-[10px] font-semibold uppercase tracking-wide border border-border bg-surface text-caption">
            {entry.difficulty === "beginner"
              ? "Beginner"
              : entry.difficulty === "intermediate"
                ? "Intermediate"
                : "Advanced"}
          </span>
        </div>
        <h1
          className="font-editorial text-4xl sm:text-5xl font-semibold text-ink leading-tight mb-4"
          style={{ fontVariationSettings: "'opsz' 64" }}
        >
          {entry.title}
        </h1>
        <p className="text-base text-body leading-relaxed">{entry.subtitle}</p>
      </header>

      {/* Body */}
      <article className="max-w-3xl mx-auto px-4 sm:px-6 pb-16">
        <SectionBlock heading="What is this?">
          <p className="text-base text-body leading-relaxed">
            {entry.definition}
          </p>
        </SectionBlock>

        <SectionBlock heading="Why does it matter?">
          <p className="text-base text-body leading-relaxed">
            {entry.whyItMatters}
          </p>
        </SectionBlock>

        {entry.formula && (
          <SectionBlock heading="Formula">
            <p className="text-[15px] font-mono text-ink bg-surface border border-border rounded-md px-3 py-2.5 inline-block break-words">
              {entry.formula}
            </p>
          </SectionBlock>
        )}

        <SectionBlock heading="Typical ranges">
          <div className="border border-border rounded-lg overflow-hidden bg-surface">
            <ul className="divide-y divide-border">
              {entry.ranges.map((range) => (
                <li
                  key={range.label}
                  className="px-4 py-3 text-base text-body flex flex-col sm:flex-row sm:items-baseline sm:gap-4"
                >
                  <span className="font-semibold text-ink whitespace-nowrap sm:basis-48">
                    {range.label}
                  </span>
                  <span className="leading-snug">{range.description}</span>
                </li>
              ))}
            </ul>
          </div>
        </SectionBlock>

        <SectionBlock heading="Worked example">
          <div className="border-l-4 border-brand bg-surface/60 px-4 py-3 rounded-r-md">
            <p className="text-base text-body leading-relaxed">
              {entry.example}
            </p>
          </div>
        </SectionBlock>

        {entry.caveat && (
          <SectionBlock heading="What this metric does not tell you">
            <p className="text-base text-caption leading-relaxed">
              {entry.caveat}
            </p>
          </SectionBlock>
        )}

        {/* Related */}
        {related.length > 0 && (
          <SectionBlock heading="Read next">
            <div className="grid gap-3 sm:grid-cols-2">
              {related.map((r) => (
                <Link
                  key={r.slug}
                  href={`/learn/${r.slug}`}
                  data-testid={`learn-related-${r.slug}`}
                  className="block rounded-md border border-border bg-surface p-3 hover:border-muted-foreground/60 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand transition-all"
                >
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-caption mb-1">
                    {r.category}
                  </p>
                  <p className="font-editorial text-base font-semibold text-ink leading-tight">
                    {r.title}
                  </p>
                </Link>
              ))}
            </div>
          </SectionBlock>
        )}
      </article>

      {/* Trust footer */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 pb-20">
        <div className="border-t border-border pt-6 text-sm text-caption leading-relaxed">
          This explainer is for educational reference only. It is not
          investment advice and does not constitute a recommendation on
          any security. YieldIQ is not a SEBI-registered Investment
          Advisor. Return to the{" "}
          <Link href="/learn" className="text-brand hover:underline">
            Learn index
          </Link>
          .
        </div>
      </section>
    </main>
  )
}

function SectionBlock({
  heading,
  children,
}: {
  heading: string
  children: React.ReactNode
}) {
  return (
    <section className="mb-8 last:mb-0">
      <h2 className="font-editorial text-xl font-semibold text-ink mb-3">
        {heading}
      </h2>
      {children}
    </section>
  )
}
