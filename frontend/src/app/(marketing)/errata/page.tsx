import type { Metadata } from "next"
import Link from "next/link"

/**
 * /errata — public model errors log.
 *
 * Lists known and fixed model errors, with severity, affected ticker
 * count, fix reference, and a one-line root-cause note. The premise
 * is simple: we publish bugs we know about. Voice matches the rest
 * of the trust surface (analyst-appendix, design tokens only, no
 * marketing language).
 *
 * Severity bands:
 *   P0 — wrong number on a bellwether or wide ticker count
 *   P1 — wrong number on a small set, or a verdict-band wobble
 *   P2 — cosmetic / single-ticker / brief window
 */

export function generateMetadata(): Metadata {
  const title = "Errata — Known model errors"
  const description =
    "Public log of known and fixed YieldIQ model errors. Date, severity, affected tickers, root cause, and fix reference for each entry."
  return {
    title,
    description,
    alternates: { canonical: "https://yieldiq.in/errata" },
    openGraph: {
      title,
      description,
      url: "https://yieldiq.in/errata",
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

type Severity = "P0" | "P1" | "P2"

interface ErrataEntry {
  date: string
  summary: string
  severity: Severity
  affected: string
  fix: string
  rootCause: string
}

const ENTRIES: ErrataEntry[] = [
  {
    date: "2026-05-02",
    summary:
      "Standalone+consolidated XBRL rows produced inflated CAGR (e.g. FOSECOIND 55% vs real 16%).",
    severity: "P0",
    affected: "294 mid-cap tickers",
    fix: "period_type='annual_synth' reclassification",
    rootCause:
      "Two filing variants for the same year were being summed before the CAGR pass. Reclassifying the synthesised annual row prevents the duplicate from entering the growth calculation.",
  },
  {
    date: "2026-05-02",
    summary:
      "NESTLEIND, TITAN, HDFCBANK showed FV=0.0 verdict=data_limited for ~30 minutes during the null-CAGR gate v1 rollout.",
    severity: "P1",
    affected: "~10 bellwethers x 30 min",
    fix: "Reverted in bccb69c",
    rootCause:
      "The first cut of the null-CAGR gate was over-aggressive and tripped on legitimate names. Reverted within the 30-minute window; v2 of the gate ships behind a validator with explicit per-sector thresholds.",
  },
  {
    date: "2026-05-01",
    summary:
      "KOTAKBANK shares_outstanding stored 5x off (99,464 lakhs vs real 19,900). Caused PE 3.9x in peer cohorts.",
    severity: "P1",
    affected: "1 ticker (peer cohort impact)",
    fix: "Direct UPDATE; upstream ingest investigation ongoing",
    rootCause:
      "Unit-jump corruption in the upstream feed slipped past the validator suite. The direct fix restored the correct count; the broader question of why the validator did not catch a 5x jump is still open.",
  },
  {
    date: "2026-04-29",
    summary:
      "INFY DCF rendered Rs 16.85 (USD-tagged financials being treated as INR).",
    severity: "P1",
    affected: "1 ticker x ~6 hours",
    fix: "Canonical price cascade",
    rootCause:
      "USD-denominated line items were entering the INR DCF. The canonical price cascade now resolves currency before any per-share computation runs.",
  },
]

function severityClasses(sev: Severity): string {
  // Token-only colours; no hard-coded brand hexes.
  switch (sev) {
    case "P0":
      return "bg-red-50 text-red-700 border-red-200"
    case "P1":
      return "bg-amber-50 text-amber-700 border-amber-200"
    case "P2":
      return "bg-blue-50 text-blue-700 border-blue-200"
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

function EntryCard({ entry }: { entry: ErrataEntry }) {
  return (
    <article className="py-5 border-b border-border last:border-b-0">
      <div className="flex flex-wrap items-center gap-3 mb-2">
        <time className="font-mono text-xs text-caption">{entry.date}</time>
        <span
          className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${severityClasses(
            entry.severity
          )}`}
        >
          {entry.severity}
        </span>
        <span className="text-xs text-caption">{entry.affected}</span>
      </div>
      <h3 className="text-sm font-semibold text-ink mb-2 leading-snug">
        {entry.summary}
      </h3>
      <p className="text-sm text-body leading-relaxed mb-2">
        {entry.rootCause}
      </p>
      <p className="text-xs text-caption">
        <span className="font-semibold uppercase tracking-wider mr-1">Fix:</span>
        {entry.fix}
      </p>
    </article>
  )
}

export default function ErrataPage() {
  return (
    <main className="bg-bg text-body">
      {/* ── Hero ───────────────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 pt-16 pb-12">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-4">
          Errata
        </p>
        <h1
          className="font-editorial text-4xl sm:text-5xl font-semibold text-ink leading-tight mb-6"
          style={{ fontVariationSettings: "'opsz' 64" }}
        >
          Known model errors
        </h1>
        <p className="text-base text-body leading-relaxed">
          A public log of model bugs we found and fixed. Each entry has
          a date, a severity, the rough blast radius, a root-cause note,
          and the fix reference.
        </p>
      </section>

      {/* ── Severity legend ────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-8 border-t border-border">
        <SectionHeading eyebrow="Legend" title="Severity bands" />
        <ul className="space-y-2 text-sm text-body">
          <li>
            <span
              className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border mr-2 ${severityClasses(
                "P0"
              )}`}
            >
              P0
            </span>
            Wrong number on a bellwether, or a wide ticker-count impact.
          </li>
          <li>
            <span
              className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border mr-2 ${severityClasses(
                "P1"
              )}`}
            >
              P1
            </span>
            Wrong number on a small set, or a verdict-band wobble.
          </li>
          <li>
            <span
              className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border mr-2 ${severityClasses(
                "P2"
              )}`}
            >
              P2
            </span>
            Cosmetic, single-ticker, or a brief window with limited
            blast radius.
          </li>
        </ul>
      </section>

      {/* ── Entries ────────────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-8 border-t border-border">
        <SectionHeading
          eyebrow="Log"
          title="Entries (most recent first)"
        />
        <div className="rounded-2xl border border-border bg-surface px-5">
          {ENTRIES.map((entry, idx) => (
            <EntryCard key={`${entry.date}-${idx}`} entry={entry} />
          ))}
        </div>
      </section>

      {/* ── Footer note ────────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border">
        <p className="text-sm text-body leading-relaxed">
          We publish bugs we know about. If you find one, write to{" "}
          <a
            href="mailto:hello@yieldiq.in"
            className="text-brand hover:underline underline-offset-4"
          >
            hello@yieldiq.in
          </a>
          .
        </p>

        <div className="mt-10 pt-6 border-t border-border flex flex-wrap gap-4 text-sm">
          <Link
            href="/methodology"
            className="text-body hover:text-ink transition-colors"
          >
            Methodology
          </Link>
          <Link
            href="/team"
            className="text-body hover:text-ink transition-colors"
          >
            Team
          </Link>
          <Link
            href="/status"
            className="text-body hover:text-ink transition-colors"
          >
            Status
          </Link>
          <Link
            href="/about"
            className="text-body hover:text-ink transition-colors"
          >
            About
          </Link>
        </div>
      </section>
    </main>
  )
}
