// frontend/src/config/pricing.ts
// All display prices live here. Edit values to change what users see on the
// pricing page, the home page quota banner, the tax-report paywalls, etc.
//
// IMPORTANT: this file controls DISPLAY only. Razorpay subscription plans are
// minted server-side via the Subscriptions API. To wire the actual payment
// flow, set the env vars referenced by backend/routers/payments.py
// (RAZORPAY_PLAN_ID_ANALYST_MONTHLY, _ANALYST_ANNUAL, _PRO_MONTHLY,
// _PRO_ANNUAL, _PAYG, etc.) in Railway. The frontend reads nothing from
// those env vars — it reads display values from here, then asks the backend
// to mint a subscription using the env-var plan IDs.
//
// SEBI note: copy in this file is user-facing. Stick to neutral, descriptive
// tier and feature vocabulary — describe what the tier includes, not what a
// user should do with their money. (See scripts/check_sebi_words.py for the
// enforced vocabulary categories.)

export type TierId = "free" | "analyst" | "pro" | "payg" | "student"
export type BillingCadence = "monthly" | "annual" | "one_time"

export interface PriceVariant {
  cadence: BillingCadence
  priceInr: number | null // null → renders as "Coming soon" / "—"
  // No upgradeLink: backend mints via /api/v1/payments/create-subscription.
}

export interface PricingTier {
  id: TierId
  name: string // Display name
  tagline: string // One-line description
  features: readonly string[] // Feature bullets (display-only; pricing page uses its own structured list)
  variants: readonly PriceVariant[]
}

// Initial values preserve the prices currently rendered on /pricing as of
// the v7 main branch. This PR only moves the *numbers* into config; tier
// names, taglines, and feature copy on the pricing page are unchanged.
export const PRICING_TIERS: readonly PricingTier[] = [
  {
    id: "free",
    name: "Free",
    tagline: "No credit card required",
    features: [
      "5 deep analyses per day",
      "All 2,300+ NSE & BSE stocks searchable",
      "DCF Fair Value + Margin of Safety",
      "10-stock watchlist",
    ],
    variants: [{ cadence: "monthly", priceInr: 0 }],
  },
  {
    id: "analyst",
    name: "Analyst",
    tagline: "The sweet spot for serious DIY investors.",
    features: [
      "Unlimited analyses",
      "Unlimited watchlist & alerts",
      "Portfolio Prism + Portfolio Health score",
      "AI summaries (sub-second)",
      "Tax Report (capital gains calc)",
    ],
    variants: [
      { cadence: "monthly", priceInr: 799 },
      { cadence: "annual", priceInr: 4999 },
    ],
  },
  {
    id: "pro",
    name: "Pro",
    tagline: "For power users, bloggers, and advisors.",
    features: [
      "Everything in Analyst",
      "CSV + PDF export of any analysis",
      "API access (100 req/day)",
      "Save + share custom screens",
    ],
    variants: [
      { cadence: "monthly", priceInr: 1499 },
      { cadence: "annual", priceInr: 9999 },
    ],
  },
  {
    id: "student",
    name: "Student / CA articleship",
    tagline: "~75% off Analyst. Verified students and articleship trainees only.",
    features: [
      "5 deep analyses per day (same as Analyst)",
      "Watchlist + portfolio",
      "Auto-expires when graduation / articleship date passes",
    ],
    variants: [{ cadence: "monthly", priceInr: 199 }],
  },
  {
    id: "payg",
    name: "Pay-as-you-go",
    tagline: "24-hour full access to a single stock.",
    features: [
      "Prism, Fair Value, scenarios, Moat, AI summary",
      "Shareable Report Card",
    ],
    variants: [{ cadence: "one_time", priceInr: 99 }],
  },
] as const

// Helpers
export const tierById = (id: TierId): PricingTier | undefined =>
  PRICING_TIERS.find((t) => t.id === id)

export const variantFor = (
  id: TierId,
  cadence: BillingCadence
): PriceVariant | undefined => tierById(id)?.variants.find((v) => v.cadence === cadence)

export const formatPrice = (inr: number | null): string =>
  inr === null ? "Coming soon" : `₹${inr.toLocaleString("en-IN")}`

// Convenience: read a price as a formatted display string, or a fallback
// label when the variant is missing or null. Used by surfaces outside the
// pricing page (home quota banner, tax-report paywall) where we only need
// one specific price interpolated into surrounding copy.
export const priceLabel = (id: TierId, cadence: BillingCadence): string =>
  formatPrice(variantFor(id, cadence)?.priceInr ?? null)
