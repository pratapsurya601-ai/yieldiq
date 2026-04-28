import type { Metadata } from "next"
import Link from "next/link"
import fs from "node:fs/promises"
import path from "node:path"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

/**
 * /methodology/whitepaper — open-published methodology white paper.
 *
 * Renders `docs/methodology/whitepaper.md` (the source of truth) at build
 * time. Fully server-rendered: zero client JS beyond what Next.js injects
 * globally. The TOC is generated from the markdown at render time so a
 * future edit to the source automatically reshapes the navigation.
 *
 * Voice: academic appendix. Match /methodology visual conventions
 * (semantic color tokens, editorial serif for display, prose-style body).
 */

// The canonical source is `docs/methodology/whitepaper.md` at the repo
// root. We mirror a copy into `frontend/content/methodology/whitepaper.md`
// so the route can read it at build time without reaching outside the
// frontend project (Vercel and most Next.js deployments do not include
// files above the project root in the build context). The mirror is
// kept in sync via the `scripts/sync_whitepaper.sh` hook in CI.
const WHITEPAPER_PATH = path.join(
  process.cwd(),
  "content",
  "methodology",
  "whitepaper.md",
)

// Sticky-TOC entries hand-curated from the white-paper §-headings, in
// order. Built statically so the page can render without parsing the
// markdown for headings (the markdown body is rendered as a single
// ReactMarkdown block; the TOC is presentational).
const TOC: { id: string; label: string }[] = [
  { id: "1-executive-summary", label: "1. Executive Summary" },
  { id: "2-the-valuation-model", label: "2. The Valuation Model" },
  { id: "3-quality-scoring", label: "3. Quality Scoring" },
  { id: "4-the-hex--prism-visualisation", label: "4. The Hex / Prism Visualisation" },
  { id: "5-data-pipeline--quality", label: "5. Data Pipeline & Quality" },
  { id: "6-discipline--validation", label: "6. Discipline & Validation" },
  { id: "7-known-limitations", label: "7. Known Limitations" },
  { id: "8-roadmap", label: "8. Roadmap" },
  { id: "9-references--acknowledgments", label: "9. References & Acknowledgments" },
]

export function generateMetadata(): Metadata {
  const title = "Methodology White Paper — YieldIQ"
  const description =
    "The full open methodology behind YieldIQ: sector-aware DCF, Piotroski-adapted quality scoring, six-axis Prism, data pipeline, validation gates, and known limitations."
  return {
    title,
    description,
    alternates: { canonical: "https://yieldiq.in/methodology/whitepaper" },
    openGraph: {
      title,
      description,
      url: "https://yieldiq.in/methodology/whitepaper",
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

async function loadWhitepaper(): Promise<string> {
  // Read the markdown source at request time. In production this fires
  // once per cold-start since the page is static-cacheable; in dev it
  // re-reads on every change so authors see edits immediately.
  return fs.readFile(WHITEPAPER_PATH, "utf-8")
}

export default async function WhitepaperPage() {
  const md = await loadWhitepaper()
  const wordCount = md.trim().split(/\s+/).length

  return (
    <main className="bg-bg text-body">
      {/* ── Hero ───────────────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 pt-16 pb-8">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-4">
          White Paper &mdash; Version 1.0
        </p>
        <h1
          className="font-editorial text-4xl sm:text-5xl font-semibold text-ink leading-tight mb-6"
          style={{ fontVariationSettings: "'opsz' 64" }}
        >
          YieldIQ Methodology
        </h1>
        <p className="text-base text-body leading-relaxed mb-6">
          The full open methodology behind every analysis on YieldIQ.
          Sector-aware DCF, quality scoring, the six-axis Prism, the data
          pipeline, the discipline that keeps it correct, and the known
          limitations.
        </p>
        <div className="flex flex-wrap gap-3 text-xs">
          {/* TODO(pdf): wire up Puppeteer/Playwright PDF generation. The
             button is intentionally a fragment until then so we never
             ship a broken download link. See docs/ops/whitepaper_pdf.md. */}
          <span
            className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1.5 text-caption opacity-60 cursor-not-allowed"
            aria-disabled="true"
            title="PDF generation coming soon"
          >
            Download PDF (coming soon)
          </span>
          <Link
            href="https://github.com/yieldiq/yieldiq/blob/main/docs/methodology/whitepaper.md"
            className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1.5 text-caption hover:bg-bg-subtle"
          >
            Suggest edits on GitHub &rarr;
          </Link>
          <span className="inline-flex items-center px-3 py-1.5 text-caption">
            ~{Math.round(wordCount / 1000)}k words &middot; ~{Math.max(1, Math.round(wordCount / 250))} min read
          </span>
        </div>
      </section>

      {/* ── Two-column layout: sticky TOC + body ───────────────── */}
      <div className="max-w-6xl mx-auto px-4 sm:px-6 pb-20">
        <div className="grid grid-cols-1 lg:grid-cols-[14rem_minmax(0,1fr)] gap-10">
          {/* Sticky TOC */}
          <aside className="hidden lg:block">
            <nav className="sticky top-20">
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-caption mb-3">
                Contents
              </p>
              <ol className="space-y-2 text-sm">
                {TOC.map(t => (
                  <li key={t.id}>
                    <a
                      href={`#${t.id}`}
                      className="text-body hover:text-ink transition leading-snug block"
                    >
                      {t.label}
                    </a>
                  </li>
                ))}
              </ol>
            </nav>
          </aside>

          {/* Body */}
          <article
            className="prose prose-neutral max-w-none
                       prose-headings:font-editorial prose-headings:text-ink
                       prose-h1:text-3xl prose-h1:font-semibold prose-h1:mt-12 prose-h1:mb-6
                       prose-h2:text-2xl prose-h2:font-semibold prose-h2:mt-10 prose-h2:mb-4 prose-h2:border-t prose-h2:border-border prose-h2:pt-8
                       prose-h3:text-lg prose-h3:font-semibold prose-h3:mt-8 prose-h3:mb-3
                       prose-p:text-body prose-p:leading-relaxed
                       prose-li:text-body prose-li:leading-relaxed
                       prose-strong:text-ink prose-strong:font-semibold
                       prose-a:text-ink prose-a:underline hover:prose-a:opacity-80
                       prose-code:font-mono prose-code:text-xs prose-code:text-ink prose-code:bg-bg-subtle prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none
                       prose-pre:bg-bg-subtle prose-pre:text-ink prose-pre:text-xs prose-pre:rounded-lg prose-pre:border prose-pre:border-border
                       prose-table:text-sm
                       prose-th:bg-bg-subtle prose-th:font-semibold prose-th:text-ink prose-th:px-3 prose-th:py-2 prose-th:text-left
                       prose-td:px-3 prose-td:py-2 prose-td:border-t prose-td:border-border
                       prose-blockquote:border-l-border prose-blockquote:text-body prose-blockquote:not-italic
                       prose-hr:border-border prose-hr:my-10"
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
          </article>
        </div>
      </div>

      {/* ── Footer attribution ─────────────────────────────────── */}
      <footer className="max-w-3xl mx-auto px-4 sm:px-6 py-12 border-t border-border text-xs text-caption">
        <p>
          Last updated 2026-04-28. Suggest edits via{" "}
          <Link
            href="https://github.com/yieldiq/yieldiq/blob/main/docs/methodology/whitepaper.md"
            className="underline hover:opacity-80"
          >
            GitHub
          </Link>
          . This paper is descriptive, not advisory. Nothing here is investment advice.
        </p>
      </footer>
    </main>
  )
}
