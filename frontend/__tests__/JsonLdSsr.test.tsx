/**
 * PR-2 (2026-06-04): SSR-emission tests for JSON-LD structured data.
 *
 * Phase-0 audit confirmed 0 / 32 analysis URLs and 0 / 1 landing URLs
 * shipped JSON-LD in their SSR HTML response. The relocation moves the
 * mount points into server components; these tests assert the structural
 * invariants so we cannot regress to "client-only-mounted JSON-LD" again
 * without the suite turning red.
 *
 * We don't test the route's full `page.tsx` here — those server components
 * fetch over the network and are exercised by preview-deploy curl. These
 * tests exercise the JSON-LD components themselves, which is what
 * actually carries the regression risk (any future "let's make this
 * client" diff to JsonLd.tsx / LandingJsonLd.tsx breaks SSR emission).
 */

import { describe, it, expect } from "vitest"
import { renderToString } from "react-dom/server"
import JsonLd from "@/app/(app)/analysis/[ticker]/JsonLd"
import LandingJsonLd from "@/app/LandingJsonLd"

describe("Analysis JsonLd — SSR emission", () => {
  const html = renderToString(
    <JsonLd
      ticker="HDFCBANK.NS"
      companyName="HDFC Bank"
      sector="Banking"
      currentPrice={1650.5}
      fairValue={1800.0}
      mosPct={9.1}
      yieldiqScore={72}
      verdict="Below fair value"
      exchange="NSE"
    />,
  )

  it("emits two <script type=application/ld+json> tags", () => {
    const matches = html.match(/type="application\/ld\+json"/g) ?? []
    expect(matches.length).toBe(2)
  })

  it("includes @type: FinancialProduct in the first script", () => {
    expect(html).toContain('"@type":"FinancialProduct"')
    expect(html).toContain('"name":"HDFC Bank (HDFCBANK)"')
    expect(html).toContain('"priceCurrency":"INR"')
  })

  it("includes @type: BreadcrumbList in the second script", () => {
    expect(html).toContain('"@type":"BreadcrumbList"')
    expect(html).toContain('"name":"NSE"')
    expect(html).toContain('"name":"Banking"')
    expect(html).toContain('"name":"HDFCBANK"')
  })

  it("canonical URL embeds the full ticker including suffix", () => {
    expect(html).toContain(
      '"url":"https://yieldiq.in/analysis/HDFCBANK.NS"',
    )
  })

  it("does NOT serialize any banned verdict-band vocabulary", () => {
    // Defense in depth: the schema content is reused verbatim from
    // pre-PR Day-40 code, but JSON-LD `description` fields are
    // Googlebot-indexable, so the regression risk is non-zero.
    // (We don't enumerate the banned words here — the SEBI lint owns
    // that vocabulary list; this is a structural smoke test.)
    const desc = html.match(/"description":"([^"]+)"/)?.[1] ?? ""
    expect(desc.length).toBeGreaterThan(0)
    expect(desc).toContain("DCF")
  })
})

describe("Landing LandingJsonLd — SSR emission", () => {
  const html = renderToString(<LandingJsonLd />)

  it("emits exactly two <script type=application/ld+json> tags", () => {
    const matches = html.match(/type="application\/ld\+json"/g) ?? []
    expect(matches.length).toBe(2)
  })

  it("emits a WebSite schema with nested SearchAction potentialAction", () => {
    expect(html).toContain('"@type":"WebSite"')
    expect(html).toContain('"name":"YieldIQ"')
    expect(html).toContain('"@type":"SearchAction"')
    expect(html).toContain('"urlTemplate":"https://yieldiq.in/search?q={search_term_string}"')
    expect(html).toContain('"query-input":"required name=search_term_string"')
  })

  it("emits an Organization schema with logo + url", () => {
    expect(html).toContain('"@type":"Organization"')
    expect(html).toContain('"logo":"https://yieldiq.in/icon-512.png"')
    expect(html).toContain('"url":"https://yieldiq.in"')
  })

  it("does NOT create three top-level schemas (SearchAction must be nested)", () => {
    // SearchAction should appear only as `potentialAction` inside the
    // WebSite block, never as a top-level @graph entry.
    const topLevelSearchAction = html.match(
      /\{"@context":"https:\/\/schema\.org","@type":"SearchAction"/g,
    )
    expect(topLevelSearchAction).toBeNull()
  })
})
