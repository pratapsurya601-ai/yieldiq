/**
 * Day-40 (2026-05-20): SSR-only JSON-LD emitter for /analysis/[ticker].
 *
 * Previously YieldIQ emitted ZERO structured data — Google's Rich
 * Results crawler saw FV / MoS / score as plain text and could not
 * surface the page in financial-result rich snippets.
 *
 * Two schemas emitted:
 *
 *   1. FinancialProduct — describes the analysed stock with offer
 *      price (CMP) and the YieldIQ fair-value estimate as a custom
 *      additionalProperty. Google's FinancialProduct rich result
 *      shows up for finance-related queries.
 *
 *   2. BreadcrumbList — Exchange → Sector → Stock breadcrumb. Eligible
 *      for the breadcrumb rich result on search.
 *
 * NOT a client component — renders pure HTML <script> tags via SSR.
 * Imported into PublicAnalysis after data fetch so we have the live
 * values at render time.
 *
 * Validate at https://search.google.com/test/rich-results with any
 * production analysis URL after deploy.
 */

interface JsonLdProps {
  ticker: string
  companyName: string
  sector: string | null | undefined
  currentPrice: number | null | undefined
  fairValue: number | null | undefined
  mosPct: number | null | undefined
  yieldiqScore: number | null | undefined
  verdict: string
  exchange: "NSE" | "BSE"
}

export default function JsonLd({
  ticker,
  companyName,
  sector,
  currentPrice,
  fairValue,
  mosPct,
  yieldiqScore,
  verdict,
  exchange,
}: JsonLdProps) {
  const displayTicker = ticker.replace(/\.(NS|BO)$/i, "")
  const canonicalUrl = `https://yieldiq.in/analysis/${ticker}`

  // FinancialProduct schema. Google's spec supports `category`,
  // `offers`, and `additionalProperty` for custom fields like
  // YieldIQ score + verdict.
  const financialProduct: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "FinancialProduct",
    name: `${companyName} (${displayTicker})`,
    description:
      `Independent DCF-based fair-value estimate for ${companyName} ` +
      `(${exchange}: ${displayTicker}). Updated daily.`,
    url: canonicalUrl,
    category: sector ?? "Equity",
    provider: {
      "@type": "Organization",
      name: "YieldIQ",
      url: "https://yieldiq.in",
    },
  }

  // offers price (current market price)
  if (currentPrice && currentPrice > 0) {
    financialProduct.offers = {
      "@type": "Offer",
      price: currentPrice.toFixed(2),
      priceCurrency: "INR",
      availability: "https://schema.org/InStock",
    }
  }

  // YieldIQ-specific fields as additionalProperty entries
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
      name: "Margin of Safety",
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

  // BreadcrumbList schema. Exchange → Sector → Stock.
  const breadcrumbList = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      {
        "@type": "ListItem",
        position: 1,
        name: exchange,
        item: `https://yieldiq.in/stocks?exchange=${exchange.toLowerCase()}`,
      },
      ...(sector
        ? [
            {
              "@type": "ListItem",
              position: 2,
              name: sector,
              item: `https://yieldiq.in/stocks?sector=${encodeURIComponent(sector)}`,
            },
          ]
        : []),
      {
        "@type": "ListItem",
        position: sector ? 3 : 2,
        name: displayTicker,
        item: canonicalUrl,
      },
    ],
  }

  return (
    <>
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(financialProduct) }}
        data-testid="jsonld-financialproduct"
      />
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbList) }}
        data-testid="jsonld-breadcrumb"
      />
    </>
  )
}
