import type { Metadata } from "next"

interface Props {
  params: Promise<{ ticker: string }>
}

// ── SEBI title-leak fix (2026-05-26) ────────────────────────────────────
//
// Previously the analysis page tab title embedded the verdict-band label
// from /prism (e.g. "Deep value region", "Fairly priced", "Overvalued
// territory") and the og-data backend title (e.g. "Notably Undervalued").
// These strings ended up in browser tabs, Google snippets, social cards,
// and Twitter previews — surfaces the `check_sebi_words.py` lint cannot
// reach because they are derived from backend data at request time, not
// from source-code string literals.
//
// SEBI IA Regs 2013 treat prescriptive valuation verdicts as
// investment advice without registration. YieldIQ is not a SEBI-
// registered IA, so we strip ALL verdict vocabulary from <title>,
// <meta name="description">, og:title, og:description, twitter:title,
// and twitter:description.
//
// New format (no verdict language anywhere):
//   title:        "<Company Name> (<TICKER>) — Analysis | YieldIQ"
//   description:  "<Company> analysis — <size>-cap <sector>. DCF fair
//                  value, peer comparison, historical financials."
//
// We still hit /prism for the company_name + sector + market_cap_cr meta
// so the tab title carries the human-readable company name rather than
// just the symbol. og-data is no longer consulted for title/description
// (it returns verdict-laden strings); only the og-image URL and the
// data_limited / under-review flags are still honored, because those
// drive robots: noindex on degraded pages (unchanged from the previous
// implementation).

const UNDER_REVIEW_VERDICTS = new Set([
  "data_limited",
  "unavailable",
  "under_review",
  "low_confidence",
])

function neutralTitle(displayTicker: string, companyName: string): string {
  // Always include "Analysis" and "YieldIQ"; include the company name
  // when we have it, fall back to ticker-only when /prism returned null.
  return companyName
    ? `${companyName} (${displayTicker}) — Analysis | YieldIQ`
    : `${displayTicker} — Analysis | YieldIQ`
}

// Map raw market_cap_cr (₹ crores) to a neutral size bucket. Buckets are
// descriptive only — "large-cap" / "mid-cap" / "small-cap" / "micro-cap"
// are SEBI-friendly factual categories (the same buckets AMFI uses for
// its half-yearly stock classification).
function marketCapBucket(marketCapCr: number | null): string {
  if (marketCapCr == null || !Number.isFinite(marketCapCr) || marketCapCr <= 0) {
    return ""
  }
  if (marketCapCr >= 200_000) return "large-cap"
  if (marketCapCr >= 20_000) return "mid-cap"
  if (marketCapCr >= 5_000) return "small-cap"
  return "micro-cap"
}

function neutralDescription(
  displayTicker: string,
  companyName: string,
  sector: string,
  marketCapCr: number | null,
): string {
  const subject = companyName || displayTicker
  const bucket = marketCapBucket(marketCapCr)
  const sectorPhrase = sector ? sector.trim().toLowerCase() : ""
  // Build a neutral one-liner. Examples:
  //   "HDFC Bank analysis — large-cap financial services. DCF fair value, peer comparison, historical financials."
  //   "RELIANCE analysis — DCF fair value, peer comparison, historical financials."
  const sizeAndSector = [bucket, sectorPhrase].filter(Boolean).join(" ")
  const lead = sizeAndSector
    ? `${subject} analysis — ${sizeAndSector}.`
    : `${subject} analysis.`
  return `${lead} DCF fair value, peer comparison, historical financials.`
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { ticker } = await params
  const displayTicker = ticker.replace(".NS", "").replace(".BO", "")

  const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://api.yieldiq.in"
  let ogData: Record<string, unknown> | null = null
  let prismData: Record<string, unknown> | null = null
  try {
    // /prism is the canonical source for company_name, sector, and
    // market_cap_cr (see backend/services/prism_service.py:_baseline_payload).
    // /og-data is still consulted ONLY for the under-review / data_limited
    // flags that drive robots:noindex — its title/description fields are
    // ignored on purpose (they embed verdict vocabulary).
    const [ogRes, prismRes] = await Promise.all([
      fetch(`${API_URL}/api/v1/analysis/${ticker}/og-data`, {
        next: { revalidate: 60 },
      }),
      fetch(`${API_URL}/api/v1/prism/${ticker}`, {
        next: { revalidate: 60 },
      }),
    ])
    if (ogRes.ok) ogData = await ogRes.json()
    if (prismRes.ok) prismData = await prismRes.json()
  } catch {
    // Fall through to ticker-only defaults — never throw from metadata.
  }

  const companyName =
    typeof prismData?.company_name === "string"
      ? (prismData.company_name as string).trim()
      : ""
  const sector =
    typeof prismData?.sector === "string"
      ? (prismData.sector as string).trim()
      : ""
  const marketCapCr =
    typeof prismData?.market_cap_cr === "number"
      ? (prismData.market_cap_cr as number)
      : null

  // Under-review / data_limited detection drives robots:noindex only.
  // Title + description are now ALWAYS the neutral form — no verdict
  // vocabulary on any surface, ever.
  const verdict =
    typeof ogData?.verdict === "string" ? (ogData.verdict as string) : ""
  const backendStatus =
    typeof ogData?.status === "string" ? (ogData.status as string) : ""
  const dataLimitedFlag =
    typeof ogData?.data_limited === "boolean"
      ? (ogData.data_limited as boolean)
      : false
  const prismDataLimited =
    typeof prismData?.data_limited === "boolean"
      ? (prismData.data_limited as boolean)
      : false
  const isUnderReview =
    UNDER_REVIEW_VERDICTS.has(verdict) ||
    UNDER_REVIEW_VERDICTS.has(backendStatus) ||
    dataLimitedFlag ||
    prismDataLimited

  const title = neutralTitle(displayTicker, companyName)
  const description = neutralDescription(
    displayTicker,
    companyName,
    sector,
    marketCapCr,
  )

  // Use the dynamic OG image route — generates a 1200x630 PNG. The image
  // ITSELF may still render verdict text (separate workstream); this PR
  // only kills the leak in text-meta tags.
  const ogImageUrl = `https://yieldiq.in/api/og/${ticker}`

  return {
    title,
    description,
    robots: isUnderReview ? { index: false, follow: false } : undefined,
    alternates: {
      canonical: `https://yieldiq.in/analysis/${ticker}`,
    },
    openGraph: {
      title,
      description,
      url: `https://yieldiq.in/analysis/${ticker}`,
      siteName: "YieldIQ",
      type: "website",
      images: [
        {
          url: ogImageUrl,
          width: 1200,
          height: 630,
          alt: `${companyName || displayTicker} analysis on YieldIQ`,
          type: "image/png",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [ogImageUrl],
    },
  }
}

export default function AnalysisLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <>{children}</>
}
