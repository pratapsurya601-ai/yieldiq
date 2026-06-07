/**
 * Fair-value SEO page — SSR JSON-LD emitter.
 *
 * Emits THREE schemas (Google Rich Results spec):
 *
 *   1. FinancialProduct — same shape as /analysis/[ticker] so the
 *      ticker is identifiable across both surfaces. Carries CMP +
 *      DCF fair value + Discount-to-FV + YieldIQ score.
 *
 *   2. WebPage (with breadcrumb) — anchors the page in the site
 *      hierarchy so Google can show a breadcrumb rich snippet
 *      pointing home → /fair-value/<TICKER>.
 *
 *   3. FAQPage — the section-5 Q+A rendered as `mainEntity`. Eligible
 *      for the FAQ rich result; carries the SEBI-posture answer
 *      ("not a SEBI-registered investment adviser") which is the
 *      load-bearing disclosure on the page.
 *
 * SSR only — pure HTML <script> tags. No client JS. The component is
 * imported into the server tree of page.tsx after the /api/v1/prism
 * fetch so all values are populated at render time.
 */

export interface FaqEntry {
  question: string
  answer: string
}

interface JsonLdProps {
  ticker: string
  displayTicker: string
  companyName: string
  sector: string | null | undefined
  currentPrice: number | null | undefined
  fairValue: number | null | undefined
  mosPct: number | null | undefined
  yieldiqScore: number | null | undefined
  verdict: string
  exchange: "NSE" | "BSE"
  faq: FaqEntry[]
}

export default function FairValueJsonLd({
  ticker,
  displayTicker,
  companyName,
  sector,
  currentPrice,
  fairValue,
  mosPct,
  yieldiqScore,
  verdict,
  exchange,
  faq,
}: JsonLdProps) {
  const canonicalUrl = `https://yieldiq.in/fair-value/${ticker}`

  // ── 1. FinancialProduct ────────────────────────────────────────────
  const financialProduct: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "FinancialProduct",
    name: `${companyName} (${displayTicker})`,
    description:
      `Independent DCF-based fair value for ${companyName} ` +
      `(${exchange}: ${displayTicker}). Updated daily.`,
    url: canonicalUrl,
    category: sector ?? "Equity",
    provider: {
      "@type": "Organization",
      name: "YieldIQ",
      url: "https://yieldiq.in",
    },
  }
  if (currentPrice && currentPrice > 0) {
    financialProduct.offers = {
      "@type": "Offer",
      price: currentPrice.toFixed(2),
      priceCurrency: "INR",
      availability: "https://schema.org/InStock",
    }
  }
  const additionalProperty: Record<string, unknown>[] = []
  if (fairValue && fairValue > 0) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "Fair Value (DCF estimate)",
      value: fairValue.toFixed(2),
      unitCode: "INR",
    })
  }
  if (mosPct !== null && mosPct !== undefined && Number.isFinite(mosPct)) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "Discount to FV",
      value: mosPct.toFixed(1),
      unitText: "PERCENT",
    })
  }
  if (yieldiqScore !== null && yieldiqScore !== undefined) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "YieldIQ Score (0-100)",
      value: String(yieldiqScore),
    })
  }
  if (verdict) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "Verdict",
      value: verdict,
    })
  }
  if (additionalProperty.length > 0) {
    financialProduct.additionalProperty = additionalProperty
  }

  // ── 2. WebPage with breadcrumb ─────────────────────────────────────
  const webPage = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: `${companyName} (${displayTicker}) Fair Value`,
    url: canonicalUrl,
    isPartOf: {
      "@type": "WebSite",
      name: "YieldIQ",
      url: "https://yieldiq.in",
    },
    breadcrumb: {
      "@type": "BreadcrumbList",
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: "YieldIQ",
          item: "https://yieldiq.in",
        },
        {
          "@type": "ListItem",
          position: 2,
          name: "Fair Value",
          item: "https://yieldiq.in/fair-value",
        },
        {
          "@type": "ListItem",
          position: 3,
          name: displayTicker,
          item: canonicalUrl,
        },
      ],
    },
  }

  // ── 3. FAQPage ─────────────────────────────────────────────────────
  const faqPage = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faq.map((qa) => ({
      "@type": "Question",
      name: qa.question,
      acceptedAnswer: {
        "@type": "Answer",
        text: qa.answer,
      },
    })),
  }

  return (
    <>
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(financialProduct) }}
        data-testid="fv-jsonld-financialproduct"
      />
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(webPage) }}
        data-testid="fv-jsonld-webpage"
      />
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqPage) }}
        data-testid="fv-jsonld-faqpage"
      />
    </>
  )
}
