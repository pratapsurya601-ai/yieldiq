/**
 * SSR-only JSON-LD for /funds/[scheme_code].
 *
 * Two schemas:
 *   1. FinancialProduct — describes the scheme. AMC, category, plan,
 *      Riskometer level surfaced as additionalProperty entries. No
 *      offers price (mutual funds are subscribed/redeemed at NAV, not
 *      market price; FinancialProduct's `offers.price` semantics don't
 *      cleanly map). The YieldIQ Fund Score is included only when
 *      Phase 2 has populated it.
 *   2. BreadcrumbList — Funds → AMC → Scheme.
 *
 * Mirrors the stock-side pattern in app/(app)/analysis/[ticker]/JsonLd.tsx
 * but stays read-only — no fair value / MoS / verdict fields exist on
 * the mutual-fund surface.
 */

import type { Fund, FundReturnsCache } from "@/types/api"

interface Props {
  fund: Fund
  metrics: FundReturnsCache | null
}

export default function FundJsonLd({ fund, metrics }: Props) {
  const url = `https://yieldiq.in/funds/${encodeURIComponent(fund.scheme_code)}`

  const additionalProperty: Record<string, unknown>[] = []
  if (fund.amc) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "AMC",
      value: fund.amc,
    })
  }
  if (fund.category) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "Category",
      value: fund.category,
    })
  }
  if (fund.sub_category) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "Sub-category",
      value: fund.sub_category,
    })
  }
  if (fund.plan) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "Plan",
      value: fund.plan,
    })
  }
  if (fund.option) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "Option",
      value: fund.option,
    })
  }
  if (fund.riskometer_level) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "SEBI Riskometer",
      value: fund.riskometer_level,
    })
  }
  if (fund.inception_date) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "Inception Date",
      value: fund.inception_date,
    })
  }
  if (metrics?.yieldiq_fund_score != null) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "YieldIQ Fund Score (0-100)",
      value: String(metrics.yieldiq_fund_score),
    })
  }
  if (metrics?.ter_direct != null) {
    additionalProperty.push({
      "@type": "PropertyValue",
      name: "TER (Direct)",
      value: metrics.ter_direct.toFixed(2),
      unitText: "PERCENT",
    })
  }

  const financialProduct: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "FinancialProduct",
    name: fund.scheme_name,
    description:
      `${fund.scheme_name} by ${fund.amc}. ` +
      `NAV history, returns versus benchmark, and risk metrics on YieldIQ.`,
    url,
    category: fund.category ?? "Mutual Fund",
    provider: {
      "@type": "Organization",
      name: "YieldIQ",
      url: "https://yieldiq.in",
    },
  }
  if (additionalProperty.length > 0) {
    financialProduct.additionalProperty = additionalProperty
  }

  const breadcrumb = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      {
        "@type": "ListItem",
        position: 1,
        name: "Mutual Funds",
        item: "https://yieldiq.in/funds",
      },
      {
        "@type": "ListItem",
        position: 2,
        name: fund.amc,
        item: "https://yieldiq.in/funds",
      },
      {
        "@type": "ListItem",
        position: 3,
        name: fund.scheme_name,
        item: url,
      },
    ],
  }

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(financialProduct) }}
        data-testid="jsonld-fund-financialproduct"
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumb) }}
        data-testid="jsonld-fund-breadcrumb"
      />
    </>
  )
}
