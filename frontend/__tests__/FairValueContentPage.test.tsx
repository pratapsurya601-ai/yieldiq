/**
 * Tests for the /fair-value/[ticker] programmatic SEO page.
 *
 * Three test surfaces:
 *
 *   1. Prose content — renders H1, FV panel data, all 5 sections.
 *      We construct a synthetic view-model so the test is hermetic
 *      (no upstream /api/v1/prism fetch). The page component itself
 *      is async + does network I/O; we test the content renderer +
 *      the JSON-LD emitter directly, which is where the regression
 *      risk lives.
 *
 *   2. JSON-LD — three schemas (FinancialProduct / WebPage / FAQPage),
 *      each in its own <script type=application/ld+json> tag, and
 *      none of them serialising banned vocab.
 *
 *   3. Snapshot of the rendered prose template — guards against
 *      accidental copy regressions that re-introduce advisory tone.
 *      Snapshot lives under __tests__/__snapshots__/.
 */

import { describe, it, expect, beforeEach } from "vitest"
import { render } from "@testing-library/react"
import { renderToString } from "react-dom/server"

import FairValueContent, {
  buildFaq,
  type FairValueViewModel,
} from "@/app/(marketing)/fair-value/[ticker]/FairValueContent"
import FairValueJsonLd from "@/app/(marketing)/fair-value/[ticker]/JsonLd"

const SAMPLE_VM: FairValueViewModel = {
  ticker: "HDFCBANK.NS",
  displayTicker: "HDFCBANK",
  companyName: "HDFC Bank",
  sector: "Banking",
  currentPrice: 1650.5,
  fairValue: 1800.0,
  mosPct: 9.1,
  yieldiqScore: 72,
  verdict: "Below fair value",
  fairValueBear: 1450.0,
  fairValueBull: 2100.0,
  moatLabel: "Wide",
  fScore: 7,
  redFlagCount: 0,
  waccPct: 11.5,
  terminalGrowthPct: 4.0,
  revenueGrowthPct: 12.0,
  peers: [
    {
      ticker: "ICICIBANK",
      companyName: "ICICI Bank",
      fairValue: 1200,
      mosPct: 6.4,
    },
    {
      ticker: "KOTAKBANK",
      companyName: "Kotak Mahindra Bank",
      fairValue: 1900,
      mosPct: -3.2,
    },
    {
      ticker: "AXISBANK",
      companyName: "Axis Bank",
      fairValue: 1300,
      mosPct: 11.0,
    },
  ],
  moatPhrase:
    "HDFC Bank's moat comes from a low-cost current-and-savings deposit franchise, switching costs that keep retail accounts sticky, and an underwriting record that has produced one of the lowest credit-cost cycles in Indian private banking.",
  updatedDate: "4 Jun 2026",
}

describe("FairValueContent — page renders all required surfaces", () => {
  // RTL auto-cleans the DOM afterEach (see __tests__/setup.ts), so we
  // mount per-test rather than once at describe scope.
  let container: HTMLElement
  beforeEach(() => {
    container = render(<FairValueContent vm={SAMPLE_VM} />).container
  })

  it("renders the H1 with company + ticker + 'Fair Value Analysis'", () => {
    const h1 = container.querySelector("h1")
    expect(h1).not.toBeNull()
    expect(h1?.textContent).toContain("HDFC Bank")
    expect(h1?.textContent).toContain("HDFCBANK")
    expect(h1?.textContent).toContain("Fair Value Analysis")
  })

  it("renders the FV summary panel with CMP / FV / MoS / score / moat", () => {
    const text = container.textContent ?? ""
    expect(text).toContain("Current price")
    expect(text).toContain("Fair value")
    expect(text).toContain("Margin of safety")
    expect(text).toContain("YieldIQ score")
    expect(text).toContain("Moat")
    expect(text).toContain("Wide")
    expect(text).toContain("72 / 100")
  })

  it("renders the CTA to the full analysis page", () => {
    const links = Array.from(container.querySelectorAll("a"))
    const cta = links.find((a) =>
      a.textContent?.includes("See the full interactive analysis"),
    )
    expect(cta).toBeDefined()
    expect(cta?.getAttribute("href")).toBe("/analysis/HDFCBANK.NS")
  })

  it("renders all five section headings", () => {
    const headings = Array.from(container.querySelectorAll("h2")).map(
      (h) => h.textContent ?? "",
    )
    expect(headings).toContain("Fair value estimate")
    expect(headings).toContain("Quality snapshot")
    expect(headings).toContain("What this assumes")
    expect(
      headings.some((h) => h.includes("compares to peers")),
    ).toBe(true)
    expect(headings).toContain("Frequently asked")
  })

  it("renders the methodology link + playground CTA in the footer", () => {
    const links = Array.from(container.querySelectorAll("a"))
    expect(
      links.some((a) => a.getAttribute("href") === "/methodology"),
    ).toBe(true)
    expect(
      links.some(
        (a) => a.getAttribute("href") === "/analysis/HDFCBANK.NS/playground",
      ),
    ).toBe(true)
  })

  it("matches the prose template snapshot (SEBI-clean)", () => {
    // The serialised text is what the SEBI lint pattern would see
    // in production. Snapshot the full rendered HTML so any future
    // diff that re-introduces banned vocab fails the suite.
    expect(container.innerHTML).toMatchSnapshot()
  })
})

describe("FairValueJsonLd — emits three SSR schemas", () => {
  const faq = buildFaq(SAMPLE_VM)
  const html = renderToString(
    <FairValueJsonLd
      ticker={SAMPLE_VM.ticker}
      displayTicker={SAMPLE_VM.displayTicker}
      companyName={SAMPLE_VM.companyName}
      sector={SAMPLE_VM.sector}
      currentPrice={SAMPLE_VM.currentPrice}
      fairValue={SAMPLE_VM.fairValue}
      mosPct={SAMPLE_VM.mosPct}
      yieldiqScore={SAMPLE_VM.yieldiqScore}
      verdict={SAMPLE_VM.verdict}
      exchange="NSE"
      faq={faq}
    />,
  )

  it("emits exactly three <script type=application/ld+json> tags", () => {
    const matches = html.match(/type="application\/ld\+json"/g) ?? []
    expect(matches.length).toBe(3)
  })

  it("emits a FinancialProduct schema with INR offer + provider", () => {
    expect(html).toContain('"@type":"FinancialProduct"')
    expect(html).toContain('"name":"HDFC Bank (HDFCBANK)"')
    expect(html).toContain('"priceCurrency":"INR"')
    expect(html).toContain('"provider":{"@type":"Organization","name":"YieldIQ"')
  })

  it("emits a WebPage schema with breadcrumb pointing back to /", () => {
    expect(html).toContain('"@type":"WebPage"')
    expect(html).toContain('"@type":"BreadcrumbList"')
    expect(html).toContain('"item":"https://yieldiq.in"')
    expect(html).toContain('"item":"https://yieldiq.in/fair-value/HDFCBANK.NS"')
  })

  it("emits a FAQPage schema carrying all 4 FAQ questions", () => {
    expect(html).toContain('"@type":"FAQPage"')
    expect(html).toContain('"@type":"Question"')
    expect(html).toContain('"@type":"Answer"')
    // Every FAQ question must appear in the serialised payload.
    for (const qa of faq) {
      // JSON-escape the apostrophes the same way JSON.stringify does
      // before substring-searching.
      const needle = qa.question.replace(/"/g, '\\"')
      expect(html).toContain(needle)
    }
    // The SEBI-posture answer (load-bearing disclosure) MUST be in
    // the FAQ payload.
    expect(html).toContain("SEBI-registered investment adviser")
  })

  it("canonical URL embeds the full ticker including suffix", () => {
    expect(html).toContain(
      '"url":"https://yieldiq.in/fair-value/HDFCBANK.NS"',
    )
  })
})
