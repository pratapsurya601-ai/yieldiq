import { computeTrueMos } from "@/lib/utils"

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
  /**
   * Canonical headline Fair Value (composite IV when present, else DCF).
   * ROOT CAUSE #1 (2026-06-10) — the SEO surface MUST emit the same
   * number every user-visible "Fair Value" pill on the analysis page
   * shows. Pre-fix, this prop was the DCF-only `valuation.fair_value`
   * and the Rich Results card for HDFCBANK said "₹1,142" while the
   * page hero said "₹1,148". Callers must pass `headline_fair_value`
   * (falling back to `composite_intrinsic_value` and finally
   * `valuation.fair_value` for legacy payloads).
   */
  fairValue: number | null | undefined
  /**
   * Source of the fairValue prop above — "composite" when composite IV
   * drove the number, "dcf" when fallback to DCF, null when neither
   * usable. Influences the schema.org PropertyValue label so consumers
   * can tell DCF-only from composite at a glance.
   */
  fairValueMethod?: "composite" | "dcf" | null
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
  fairValueMethod,
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

  // Derive true (Buffett) MoS = (1 - price/fv)*100 from the props already in scope.
  const trueMosPct = computeTrueMos(fairValue ?? null, currentPrice ?? null)

  // YieldIQ-specific fields as additionalProperty entries
  const additionalProperty: Record<string, unknown>[] = []
  if (fairValue && fairValue > 0) {
    // ROOT CAUSE #1 (2026-06-10) — label the PropertyValue accurately:
    // "Fair Value (composite estimate)" when the headline came from the
    // composite IV path (DCF + peer multiples + analyst consensus),
    // "Fair Value (DCF estimate)" when only the DCF path was usable.
    const fvName =
      fairValueMethod === "composite"
        ? "Fair Value (composite estimate)"
        : "Fair Value (DCF estimate)"
    additionalProperty.push({
      "@type": "PropertyValue",
      name: fvName,
      value: fairValue.toFixed(2),
      unitCode: "INR",
    })
  }
  if (trueMosPct !== null && Number.isFinite(trueMosPct)) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "Margin of Safety",
      value: trueMosPct.toFixed(1),
      unitText: "PERCENT",
    })
  }
  if (mosPct !== null && mosPct !== undefined && Number.isFinite(mosPct)) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "Implied upside",
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
