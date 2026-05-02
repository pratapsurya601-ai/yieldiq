import Link from "next/link"

/**
 * TrustFooter — the Trust-Surface footer.
 *
 * Three columns on desktop, stacked on mobile:
 *   · Product  — internal app links
 *   · Data     — external data sources (NSE / BSE / SEBI)
 *   · Company  — About, Pricing, Blog, Contact
 *
 * Below that: the SEBI educational-use disclosure (verbatim) and a
 * dynamic copyright line. Design tokens only (bg-surface, text-body,
 * text-caption, border-border, text-ink) so this works in both themes.
 *
 * Replaces MarketingFooter for any surface that wants the full trust
 * treatment — currently the marketing group, the stocks group, and the
 * /about page.
 */
export default function TrustFooter() {
  const year = new Date().getFullYear()

  return (
    <footer
      className="bg-surface text-body border-t border-border mt-16"
      aria-labelledby="trust-footer-heading"
    >
      <h2 id="trust-footer-heading" className="sr-only">
        Site footer
      </h2>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-12">
        {/* ── Link grid ─────────────────────────────────────────── */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-10 sm:gap-8 mb-10">
          {/* Product */}
          <nav aria-labelledby="footer-product">
            <h3
              id="footer-product"
              className="text-[11px] font-bold text-caption uppercase tracking-wider mb-3"
            >
              Product
            </h3>
            <ul className="space-y-2 text-sm">
              <li>
                <Link
                  href="/discover"
                  className="text-body hover:text-ink transition-colors"
                >
                  Discover
                </Link>
              </li>
              <li>
                <Link
                  href="/discover/screener"
                  className="text-body hover:text-ink transition-colors"
                >
                  Screener
                </Link>
              </li>
              <li>
                <Link
                  href="/portfolio"
                  className="text-body hover:text-ink transition-colors"
                >
                  Portfolio
                </Link>
              </li>
              <li>
                <Link
                  href="/compare"
                  className="text-body hover:text-ink transition-colors"
                >
                  Compare
                </Link>
              </li>
            </ul>
          </nav>

          {/* Data sources */}
          <nav aria-labelledby="footer-data">
            <h3
              id="footer-data"
              className="text-[11px] font-bold text-caption uppercase tracking-wider mb-3"
            >
              Data
            </h3>
            <ul className="space-y-2 text-sm">
              <li>
                <a
                  href="https://www.nseindia.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-body hover:text-ink transition-colors"
                >
                  NSE (live)
                </a>
              </li>
              <li>
                <a
                  href="https://www.bseindia.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-body hover:text-ink transition-colors"
                >
                  BSE (live)
                </a>
              </li>
              <li>
                <a
                  href="https://www.sebi.gov.in/sebiweb/edifar/EdifarMain.do"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-body hover:text-ink transition-colors"
                >
                  SEBI EDIFAR
                </a>
              </li>
              <li>
                <a
                  href="https://www.sebi.gov.in/filings/insider-trading.html"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-body hover:text-ink transition-colors"
                >
                  Company filings
                </a>
              </li>
            </ul>
          </nav>

          {/* Company */}
          <nav aria-labelledby="footer-company">
            <h3
              id="footer-company"
              className="text-[11px] font-bold text-caption uppercase tracking-wider mb-3"
            >
              Company
            </h3>
            <ul className="space-y-2 text-sm">
              <li>
                <Link
                  href="/about"
                  className="text-body hover:text-ink transition-colors"
                >
                  About
                </Link>
              </li>
              <li>
                <Link
                  href="/team"
                  className="text-body hover:text-ink transition-colors"
                >
                  Team
                </Link>
              </li>
              <li>
                <Link
                  href="/errata"
                  className="text-body hover:text-ink transition-colors"
                >
                  Errata
                </Link>
              </li>
              <li>
                <Link
                  href="/pricing"
                  className="text-body hover:text-ink transition-colors"
                >
                  Pricing
                </Link>
              </li>
              <li>
                <Link
                  href="/blog"
                  className="text-body hover:text-ink transition-colors"
                >
                  Blog
                </Link>
              </li>
              <li>
                <Link
                  href="/how-it-works"
                  className="text-body hover:text-ink transition-colors"
                >
                  How it works
                </Link>
              </li>
              <li>
                <Link
                  href="/methodology"
                  className="text-body hover:text-ink transition-colors"
                >
                  Methodology
                </Link>
              </li>
              <li>
                <a
                  href="mailto:hello@yieldiq.in"
                  className="text-body hover:text-ink transition-colors"
                >
                  Contact
                </a>
              </li>
            </ul>
          </nav>
        </div>

        {/* ── Divider ───────────────────────────────────────────── */}
        <div className="border-t border-border pt-6 space-y-4">
          {/* Tagline + SEBI disclosure — the exact wording matters for
              the Trust-Surface claim; do not soften. */}
          <p className="text-sm text-body max-w-3xl leading-relaxed">
            YieldIQ — Model-based stock analysis for Indian markets. Not
            registered with SEBI as an investment adviser or research
            analyst. Content is educational. Not investment advice.
          </p>

          {/* Bottom row — copyright + legal links */}
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs text-caption">
            <div className="flex items-center gap-2">
              <span>
                &copy; {year} YieldIQ &middot; Made in India{" "}
                <span aria-hidden>🇮🇳</span>
              </span>
            </div>
            <div className="flex items-center gap-4">
              <Link
                href="/terms"
                className="hover:text-body transition-colors"
              >
                Terms
              </Link>
              <Link
                href="/privacy"
                className="hover:text-body transition-colors"
              >
                Privacy
              </Link>
              <Link
                href="/legal/sla"
                className="hover:text-body transition-colors"
              >
                SLA
              </Link>
              <Link
                href="/status"
                className="hover:text-body transition-colors"
              >
                Status
              </Link>
              <Link
                href="/about"
                className="hover:text-body transition-colors"
              >
                About
              </Link>
            </div>
          </div>
        </div>
      </div>
    </footer>
  )
}
