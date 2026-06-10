import type { Metadata } from "next"
import Link from "next/link"
import {
  EDUCATIONAL_TOPICS,
  getTopicsByCategory,
  type EducationalTopic,
} from "@/lib/educational-content"

/**
 * /learn — Educational Content Layer index page.
 *
 * SEO play: long-tail "what is X ratio" / "what is P/E" queries route
 * here. Each topic gets its own URL at /learn/<slug> so the index
 * functions as a hub page and the per-topic pages absorb the long tail.
 *
 * Server Component, fully SSR. Match marketing-page visual conventions
 * — hero on max-w-3xl, content area on max-w-5xl grid, semantic color
 * tokens only. No client JS beyond what Next.js injects globally.
 */

export function generateMetadata(): Metadata {
  const title = "Learn finance — Plain-English explainers for every metric"
  const description =
    "Free mini-lessons on the finance ratios behind every YieldIQ analysis: P/E, ROE, ROCE, WACC, EBITDA, FCF, NIM, CASA, and more. Definitions, ranges, and worked examples."
  return {
    title,
    description,
    alternates: { canonical: "https://yieldiq.in/learn" },
    openGraph: {
      title,
      description,
      url: "https://yieldiq.in/learn",
      siteName: "YieldIQ",
      type: "website",
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

/** Category display order — beginner-friendly first, advanced last. */
const CATEGORY_ORDER = [
  "Valuation",
  "Profitability",
  "Balance Sheet",
  "Cash Flow",
  "Growth",
  "Quality Score",
  "Risk",
  "Banking",
  "DCF Inputs",
] as const

function TopicCard({ topic }: { topic: EducationalTopic }) {
  return (
    <Link
      href={`/learn/${topic.slug}`}
      data-testid={`learn-topic-card-${topic.slug}`}
      className="block group rounded-lg border border-border bg-surface p-4 hover:border-muted-foreground/60 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 transition-all"
    >
      <div className="flex items-start justify-between gap-3 mb-1.5">
        <h3 className="font-editorial text-base font-semibold text-ink leading-tight group-hover:text-brand transition-colors">
          {topic.title}
        </h3>
        <span className="text-[10px] font-semibold uppercase tracking-wide text-caption shrink-0 border border-border bg-bg/60 rounded px-1.5 py-0.5">
          {topic.difficulty === "beginner"
            ? "Beginner"
            : topic.difficulty === "intermediate"
              ? "Intermediate"
              : "Advanced"}
        </span>
      </div>
      <p className="text-sm text-body leading-snug">{topic.subtitle}</p>
    </Link>
  )
}

export default function LearnIndexPage() {
  const groups = getTopicsByCategory()
  const totalTopics = Object.keys(EDUCATIONAL_TOPICS).length

  return (
    <main className="bg-bg text-body">
      {/* Hero */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 pt-16 pb-10">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-4">
          Learn finance
        </p>
        <h1
          className="font-editorial text-4xl sm:text-5xl font-semibold text-ink leading-tight mb-5"
          style={{ fontVariationSettings: "'opsz' 64" }}
        >
          Plain-English explainers for every metric you see on YieldIQ
        </h1>
        <p className="text-base text-body leading-relaxed">
          {totalTopics} mini-lessons covering valuation multiples, quality
          ratios, cash-flow measures, DCF inputs, and bank-specific KPIs.
          Each topic has a one-paragraph definition, why it matters,
          typical ranges, and a worked example using Indian-equity
          conventions.
        </p>
      </section>

      {/* Content — grouped by category */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 pb-20">
        {CATEGORY_ORDER.map((category) => {
          const topics = groups[category]
          if (!topics || topics.length === 0) return null
          return (
            <div
              key={category}
              className="mb-12"
              data-testid={`learn-category-${category.toLowerCase().replace(/\s+/g, "-")}`}
            >
              <header className="mb-4">
                <h2 className="font-editorial text-xl sm:text-2xl font-semibold text-ink mb-1">
                  {category}
                </h2>
                <p className="text-[12px] text-caption">
                  {topics.length} {topics.length === 1 ? "topic" : "topics"}
                </p>
              </header>
              <div className="grid gap-3 sm:grid-cols-2">
                {topics.map((topic) => (
                  <TopicCard key={topic.slug} topic={topic} />
                ))}
              </div>
            </div>
          )
        })}
      </section>

      {/* Trust footer copy */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 pb-20">
        <div className="border-t border-border pt-8">
          <p className="text-sm text-caption leading-relaxed">
            These lessons are for educational reference only. They are
            not investment advice and do not constitute guidance on any
            specific security. YieldIQ is not a SEBI-registered Investment
            Advisor. See our{" "}
            <Link href="/methodology" className="text-brand hover:underline">
              methodology
            </Link>{" "}
            for how our models work, and our{" "}
            <Link href="/legal/disclaimer" className="text-brand hover:underline">
              disclaimer
            </Link>{" "}
            for the full posture.
          </p>
        </div>
      </section>
    </main>
  )
}
