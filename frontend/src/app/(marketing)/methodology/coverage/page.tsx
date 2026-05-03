import type { Metadata } from "next"
import Link from "next/link"

/**
 * /methodology/coverage — the Coverage Tier explainer.
 *
 * Companion page to /methodology. Tells the user what Tier A / B / C
 * mean, what the seven rubric criteria are, and roughly how the
 * universe distributes across them today. Honest framing is the whole
 * point of the feature — this page should NOT minimise the existence
 * of Tier C.
 *
 * Server Component (no "use client"): zero client JS. The expected
 * universe distribution is rendered as a static estimate; live counts
 * can be wired in later from a cron-computed snapshot. We deliberately
 * label the numbers as estimates so we don't promise a freshness
 * guarantee we don't yet have.
 *
 * Visual conventions: matches /methodology — editorial serif for
 * display, semantic color tokens only, max-w-3xl content column.
 */

export function generateMetadata(): Metadata {
  const title = "Coverage Tiers — A, B, and C in YieldIQ"
  const description =
    "How YieldIQ assigns A/B/C coverage tiers per stock. The seven-criterion rubric, why we publish lower-tier names anyway, and what each tier should mean to you when you read an analysis."
  return {
    title,
    description,
    alternates: { canonical: "https://yieldiq.in/methodology/coverage" },
    openGraph: {
      title,
      description,
      url: "https://yieldiq.in/methodology/coverage",
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

function SectionHeading({ eyebrow, title }: { eyebrow: string; title: string }) {
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

interface TierCardProps {
  letter: "A" | "B" | "C"
  label: string
  estimate: string
  blurb: string
  tone: "ok" | "warn" | "limited"
}

function TierCard({ letter, label, estimate, blurb, tone }: TierCardProps) {
  const toneClasses = {
    ok: "border-emerald-200 bg-emerald-50",
    warn: "border-amber-200 bg-amber-50",
    limited: "border-zinc-300 bg-zinc-50",
  }[tone]
  const letterClasses = {
    ok: "text-emerald-700",
    warn: "text-amber-700",
    limited: "text-zinc-700",
  }[tone]
  return (
    <div className={`rounded-2xl border p-6 ${toneClasses}`}>
      <p className={`font-editorial text-5xl font-semibold mb-2 ${letterClasses}`}>
        Tier {letter}
      </p>
      <p className="text-sm font-semibold text-ink mb-1">{label}</p>
      <p className="text-xs text-caption mb-3 font-mono tabular-nums">
        Estimated universe: ~{estimate}
      </p>
      <p className="text-sm text-body leading-relaxed">{blurb}</p>
    </div>
  )
}

function Criterion({ n, name, body }: { n: string; name: string; body: string }) {
  return (
    <li className="flex gap-4 py-3 border-b border-border last:border-b-0">
      <span className="font-mono text-xs text-caption shrink-0 w-6">{n}</span>
      <div>
        <p className="text-sm font-semibold text-ink mb-0.5">{name}</p>
        <p className="text-sm text-body leading-relaxed">{body}</p>
      </div>
    </li>
  )
}

export default function CoverageMethodologyPage() {
  return (
    <main className="bg-bg text-body">
      {/* ── Hero ────────────────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 pt-16 pb-12">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-4">
          Methodology &middot; Coverage
        </p>
        <h1
          className="font-editorial text-4xl sm:text-5xl font-semibold text-ink leading-tight mb-6"
          style={{ fontVariationSettings: "'opsz' 64" }}
        >
          A, B, and C — what coverage tiers mean
        </h1>
        <p className="text-base text-body leading-relaxed">
          We publish a fair-value view for thousands of Indian-listed
          stocks. The data behind those views is not equally good. A
          twenty-year-old large-cap with audited XBRL filings, a deep
          peer cohort, and clean shareholding produces a model we trust.
          A two-quarter-old IPO does not. The single &ldquo;confidence&rdquo;
          number we used to ship flattened that gap. The coverage tier
          makes it explicit.
        </p>
      </section>

      {/* ── The three tiers ────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading eyebrow="01 — The tiers" title="Three honest labels" />
        <div className="grid sm:grid-cols-3 gap-4">
          <TierCard
            letter="A"
            label="Full-confidence modeling"
            estimate="200 stocks"
            tone="ok"
            blurb="Meets all seven rubric criteria. Deep history, broad cohort, large float, no validator warnings. The model output is as good as our pipeline can make it."
          />
          <TierCard
            letter="B"
            label="Partial coverage"
            estimate="800 stocks"
            tone="warn"
            blurb="Five or six of seven criteria met, with at least the relaxed floors holding. Useful as a starting point; expect the model to be wider on assumptions you would normally pin down."
          />
          <TierCard
            letter="C"
            label="Limited coverage"
            estimate="1,200 stocks"
            tone="limited"
            blurb="Recent listings, micro-caps, thin cohorts, or significant data gaps. We still publish a view because absence of coverage is itself misleading — but treat the numbers as directional, not load-bearing."
          />
        </div>
        <p className="mt-4 text-xs text-caption">
          Universe counts are estimates from the canary-50 sample
          distribution and will be replaced with cron-computed live
          counts in a later pass.
        </p>
      </section>

      {/* ── The rubric ─────────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading eyebrow="02 — The rubric" title="Seven criteria, equal weight" />
        <p className="mb-6 text-sm text-body leading-relaxed">
          A ticker is evaluated against seven binary criteria. Tier A
          requires all seven. Tier B requires five or six AND that the
          looser floors below hold. Everything else is Tier C.
        </p>
        <ul className="space-y-0">
          <Criterion
            n="01"
            name="Annual financial history >= 10 years"
            body="Tier A bar; Tier B floor is 5 years. Below that we cannot estimate sustainable growth or normalised margins with any honesty."
          />
          <Criterion
            n="02"
            name="Quarterly periods >= 4 (full TTM)"
            body="Trailing-twelve-month aggregates need at least four quarters. A recent listing with two quarters fails this and lands in C."
          />
          <Criterion
            n="03"
            name="Sector peer cohort >= 10"
            body="Tier A bar; Tier B floor is 5. Peer-relative checks (sector P/E, ROCE, FCF yield) become noisy with fewer than 5 comparables."
          />
          <Criterion
            n="04"
            name="Market cap >= INR 10,000 cr"
            body="Tier A bar; Tier B floor is INR 2,000 cr. Below that, float, liquidity, and analyst attention all thin out — DCF outputs become more sensitive to single-rupee data errors."
          />
          <Criterion
            n="05"
            name="No validator warnings"
            body="The data-pipeline validator (bounds + consistency + ground-truth checks) emitted zero warnings on the latest cached payload."
          />
          <Criterion
            n="06"
            name="Latest annual filing within ~18 months"
            body="A stale annual filing means we are rolling forward on possibly outdated absolute numbers. Beyond about eighteen months we do not consider the snapshot fresh."
          />
          <Criterion
            n="07"
            name="Shares outstanding present and non-zero"
            body="A surprisingly common failure mode: the data pipeline misses a unit conversion and shares-outstanding ends up zero or absent. Failing this gates per-share fair value entirely."
          />
        </ul>
      </section>

      {/* ── What it does NOT change ───────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <SectionHeading eyebrow="03 — Scope" title="Labeling only" />
        <div className="space-y-4 text-sm text-body leading-relaxed">
          <p>
            Coverage tier is purely descriptive metadata. It does not
            change the fair value, the YieldIQ score, the verdict band,
            or any input the analysis pipeline computes. A stock&rsquo;s
            tier can move from B to A overnight when a fresh annual
            filing lands without anything else changing.
          </p>
          <p>
            We deliberately keep the FV the same across tiers because
            hiding numbers behind tier walls would push users toward
            inferring quality from absence. Better to show the number
            and tell you exactly how much of our usual rigour stood
            behind it.
          </p>
        </div>
      </section>

      {/* ── CTA ──────────────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-16 border-t border-border">
        <p className="text-sm text-body mb-4">
          See the tier badge in context on any analysis page.
        </p>
        <Link
          href="/methodology"
          className="inline-flex items-center rounded-full bg-brand text-white px-5 py-2 text-sm font-medium hover:opacity-90 transition"
        >
          Back to methodology &rarr;
        </Link>
      </section>
    </main>
  )
}
