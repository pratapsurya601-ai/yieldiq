import type { Metadata } from "next"
import Link from "next/link"

/**
 * /team — public team page.
 *
 * Single-founder placeholder. Honest about the size of the operation
 * and the kind of help we'd add next. Voice matches /about and
 * /methodology — analyst tone, no marketing language, design tokens
 * only.
 */

export function generateMetadata(): Metadata {
  const title = "The team — YieldIQ"
  const description =
    "YieldIQ is built by a single founder. Solo dev, solo product, solo support — and honest about what that means."
  return {
    title,
    description,
    alternates: { canonical: "https://yieldiq.in/team" },
    openGraph: {
      title,
      description,
      url: "https://yieldiq.in/team",
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

function SectionHeading({
  eyebrow,
  title,
}: {
  eyebrow: string
  title: string
}) {
  return (
    <header className="mb-6">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-3">
        {eyebrow}
      </p>
      <h2 className="font-editorial text-2xl sm:text-3xl font-semibold text-ink">
        {title}
      </h2>
    </header>
  )
}

export default function TeamPage() {
  return (
    <main className="bg-bg text-body">
      {/* ── Hero ───────────────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 pt-16 pb-12">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-4">
          Team
        </p>
        <h1
          className="font-editorial text-4xl sm:text-5xl font-semibold text-ink leading-tight mb-6"
          style={{ fontVariationSettings: "'opsz' 64" }}
        >
          The team
        </h1>
        <p className="text-base text-body leading-relaxed">
          YieldIQ is built by a single founder. Solo dev, solo product,
          solo support.
        </p>
      </section>

      {/* ── Founder ────────────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading eyebrow="01 — Who" title="Surya Pratap" />
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            <span className="text-ink font-semibold">Founder &amp; engineer.</span>{" "}
            10+ years building data products. Background spans
            quantitative tooling, full-stack engineering, and the
            unglamorous middle of the stack where most stock-analysis
            sites quietly cut corners.
          </p>
          <p>
            Reachable directly:{" "}
            <a
              href="mailto:hello@yieldiq.in"
              className="text-brand hover:underline underline-offset-4"
            >
              hello@yieldiq.in
            </a>
            . Replies come from the same person who wrote the code.
          </p>
        </div>
      </section>

      {/* ── Why ────────────────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading eyebrow="02 — Why" title="Why we built this" />
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            Most Indian retail tools either give you a free PE chart or
            charge &#8377;15k/year for analyst reports written for
            institutions. We wanted a third option: honest model output
            with every number traceable to a filing.
          </p>
          <p>
            That means publishing the methodology, publishing the bugs
            we know about, and resisting the urge to dress model output
            up as advice. The site is small on purpose &mdash; one
            person can hold the whole thing in their head, which is the
            only honest way to ship a stock-analysis product without a
            compliance department.
          </p>
        </div>
      </section>

      {/* ── Hiring ─────────────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading
          eyebrow="03 — Next"
          title="Who we'd hire next (when we can)"
        />
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            A quant researcher with banking and insurance modelling
            experience. Sector substitutes for Altman-Z, capital
            adequacy treatment, and the mess of standalone-versus-
            consolidated reporting in Indian financials are areas
            where a second pair of eyes would change the product.
          </p>
          <p>
            If that&rsquo;s you, write to{" "}
            <a
              href="mailto:hiring@yieldiq.in"
              className="text-brand hover:underline underline-offset-4"
            >
              hiring@yieldiq.in
            </a>
            . Code, public writing, or a screenshot of a model you
            built &mdash; whatever shows the work.
          </p>
        </div>

        <div className="mt-10 pt-6 border-t border-border flex flex-wrap gap-4 text-sm">
          <a
            href="mailto:hiring@yieldiq.in"
            className="text-brand hover:underline underline-offset-4"
          >
            hiring@yieldiq.in &rarr;
          </a>
          <a
            href="https://github.com/yieldiq"
            target="_blank"
            rel="noopener noreferrer"
            className="text-body hover:text-ink transition-colors"
          >
            GitHub
          </a>
          <Link
            href="/about"
            className="text-body hover:text-ink transition-colors"
          >
            About YieldIQ
          </Link>
          <Link
            href="/methodology"
            className="text-body hover:text-ink transition-colors"
          >
            Methodology
          </Link>
          <Link
            href="/errata"
            className="text-body hover:text-ink transition-colors"
          >
            Errata
          </Link>
        </div>
      </section>
    </main>
  )
}
