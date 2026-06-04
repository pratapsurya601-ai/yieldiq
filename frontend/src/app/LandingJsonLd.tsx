/**
 * PR-2 (2026-06-04): SSR-only JSON-LD emitter for the landing page `/`.
 *
 * Before this PR the landing page shipped zero structured data. Two
 * top-level schemas are emitted (per schema.org guidance — SearchAction
 * is nested INSIDE WebSite, not a third top-level entry):
 *
 *   1. WebSite — name "YieldIQ" + url, with a `SearchAction`
 *      `potentialAction` pointing at /search?q={search_term_string}.
 *      This is what enables Google's sitelinks search box in branded
 *      SERP results.
 *
 *   2. Organization — name, url, logo, brief description sourced from
 *      existing landing copy. The logo currently points at
 *      /icon-512.png; PR-4 will replace this with the full OG card /
 *      brand logo asset.
 *
 * Pure server component — renders two <script type="application/ld+json">
 * tags via SSR. No client hydration, no JS shipped.
 */

const SITE_URL = "https://yieldiq.in"

export default function LandingJsonLd() {
  const webSite = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: "YieldIQ",
    url: SITE_URL,
    description:
      "Transparent DCF valuation for Indian equities. Every assumption " +
      "editable, every number links to its source filing.",
    potentialAction: {
      "@type": "SearchAction",
      target: {
        "@type": "EntryPoint",
        urlTemplate: `${SITE_URL}/search?q={search_term_string}`,
      },
      "query-input": "required name=search_term_string",
    },
  }

  const organization = {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "YieldIQ",
    url: SITE_URL,
    logo: `${SITE_URL}/icon-512.png`,
    description:
      "YieldIQ provides DCF-based fair value estimates for NSE and BSE " +
      "stocks. Built for self-directed long-term investors.",
  }

  return (
    <>
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(webSite) }}
        data-testid="jsonld-website"
      />
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(organization) }}
        data-testid="jsonld-organization"
      />
    </>
  )
}
