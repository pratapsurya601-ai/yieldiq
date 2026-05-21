import Link from "next/link"
import HelpNav, { HELP_TOPICS, type HelpSlug } from "./HelpNav"

/**
 * Two-column shell used by each /help/<slug> topic page. Side rail
 * (HelpNav) on the left at md+, content column on the right. On
 * mobile the nav collapses below the content. Server component.
 */
export default function HelpPageShell({
  slug,
  eyebrow,
  title,
  children,
}: {
  slug: HelpSlug
  eyebrow: string
  title: string
  children: React.ReactNode
}) {
  const topic = HELP_TOPICS.find((t) => t.slug === slug)
  const idx = HELP_TOPICS.findIndex((t) => t.slug === slug)
  const prev = idx > 0 ? HELP_TOPICS[idx - 1] : null
  const next = idx >= 0 && idx < HELP_TOPICS.length - 1 ? HELP_TOPICS[idx + 1] : null
  return (
    <main className="bg-bg text-body min-h-screen">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 pt-12 pb-16 grid grid-cols-1 md:grid-cols-[260px_1fr] gap-10">
        <aside className="order-2 md:order-1">
          <div className="md:sticky md:top-24">
            <HelpNav active={slug} />
          </div>
        </aside>
        <article className="order-1 md:order-2 max-w-3xl">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-3">
            <Link href="/help" className="hover:text-ink transition-colors">
              Help
            </Link>{" "}
            <span aria-hidden="true">/</span> {eyebrow}
          </p>
          <h1
            className="font-editorial text-3xl sm:text-4xl font-semibold text-ink leading-tight mb-2"
            style={{ fontVariationSettings: "'opsz' 64" }}
          >
            {title}
          </h1>
          {topic ? (
            <p className="text-sm text-caption mb-8">{topic.blurb}</p>
          ) : null}

          <div className="prose-help space-y-4 text-sm text-body leading-relaxed">
            {children}
          </div>

          <nav
            aria-label="Adjacent help topics"
            className="mt-12 pt-6 border-t border-border flex items-center justify-between gap-4 text-sm"
          >
            <div>
              {prev ? (
                <Link
                  href={`/help/${prev.slug}`}
                  className="text-body hover:text-ink transition-colors"
                >
                  &larr; {prev.title}
                </Link>
              ) : null}
            </div>
            <div className="text-right">
              {next ? (
                <Link
                  href={`/help/${next.slug}`}
                  className="text-brand hover:underline underline-offset-4"
                >
                  {next.title} &rarr;
                </Link>
              ) : null}
            </div>
          </nav>
        </article>
      </div>
    </main>
  )
}
