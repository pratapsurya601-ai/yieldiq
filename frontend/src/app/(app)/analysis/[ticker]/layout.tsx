import type { Metadata } from "next"
import { verdictFromMos } from "@/lib/utils"

interface Props {
  params: Promise<{ ticker: string }>
}

// Verdicts where the model could not produce a confident fair value.
// We must NEVER let the wire-format verdict ("data_limited",
// "unavailable") or its title-cased form ("Data Limited") leak into a
// page title or social-card preview — to a casual reader on Reddit /
// Twitter the phrase reads as "the app is broken" or "this stock is
// blacklisted", neither of which is true. Use neutral phrasing instead.
const UNDER_REVIEW_VERDICTS = new Set(["data_limited", "unavailable"])

// Substrings that may appear in a backend-supplied title for an under-
// review ticker. Defense in depth: even if the og-data endpoint is
// later updated to emit new variants, the title sanitizer rejects any
// of these and falls back to the neutral form.
const FORBIDDEN_TITLE_SUBSTRINGS = [
  "Data Limited",
  "Unavailable",
  "Under Review",
  "Avoid",
]

function neutralTitle(displayTicker: string): string {
  return `${displayTicker} — Fair-value analysis | YieldIQ`
}

function neutralDescription(displayTicker: string): string {
  return `Fair-value model for ${displayTicker} is under review. Inputs are being verified — full DCF, quality and moat analysis on YieldIQ.`
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { ticker } = await params
  const displayTicker = ticker.replace(".NS", "").replace(".BO", "")

  // Fetch OG data from API
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://api.yieldiq.in"
  let ogData: Record<string, unknown> | null = null
  try {
    const res = await fetch(`${API_URL}/api/v1/analysis/${ticker}/og-data`, {
      next: { revalidate: 3600 }, // Cache for 1 hour
    })
    if (res.ok) ogData = await res.json()
  } catch {
    // Fall through to defaults
  }

  const verdict =
    typeof ogData?.verdict === "string" ? (ogData.verdict as string) : ""
  const backendTitle =
    typeof ogData?.title === "string" ? (ogData.title as string) : ""
  const backendDescription =
    typeof ogData?.description === "string"
      ? (ogData.description as string)
      : ""

  // Sanitize: if the verdict is data_limited / unavailable, OR the
  // backend-supplied title contains any user-hostile substring, replace
  // both title and description with neutral copy. We do this BEFORE
  // falling back to the generic default so we never accidentally render
  // "RELIANCE — Data Limited | YieldIQ" in an og:title tag.
  const isUnderReview =
    UNDER_REVIEW_VERDICTS.has(verdict) ||
    FORBIDDEN_TITLE_SUBSTRINGS.some((s) => backendTitle.includes(s))

  // Derive the tab title's verdict from MoS (the same number rendered
  // in the page body) rather than trusting the backend-supplied
  // `title` string. Pre-launch we shipped HDFCBANK with tab=
  // "Undervalued" but body="Above Fair Value" at MoS -12.3% because
  // the og-data title was built from the verdict ENUM (which had
  // drifted from MoS in cache). verdictFromMos() in lib/utils.ts is
  // the single source of truth for both surfaces. See the helper's
  // jsdoc for the canonical thresholds.
  const mosNumber =
    typeof ogData?.mos === "number" && Number.isFinite(ogData.mos)
      ? (ogData.mos as number)
      : null
  const mosVerdict =
    mosNumber == null ? "" : verdictFromMos(mosNumber)
  // When MoS is missing we cannot trust the backend-supplied title:
  // og-data has historically returned strings like "INFY.NS Stock
  // Analysis | YieldIQ" (raw ticker, no verdict). Always rebuild from
  // displayTicker (which has .NS / .BO stripped) so the tab title is
  // clean even for tickers in a degraded data state.
  const title = isUnderReview
    ? neutralTitle(displayTicker)
    : mosVerdict
      ? `${displayTicker} — ${mosVerdict} | YieldIQ`
      : `${displayTicker} — Stock Analysis | YieldIQ`

  const description = isUnderReview
    ? neutralDescription(displayTicker)
    : backendDescription ||
      `Free DCF valuation for ${displayTicker}. See its fair-value estimate, margin of safety, and quality scores.`

  // Use the dynamic OG image route — generates a 1200x630 PNG
  // with the stock's verdict, fair value, score, etc. baked in
  const ogImageUrl = `https://yieldiq.in/api/og/${ticker}`

  return {
    title,
    description,
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
          alt: `${displayTicker} stock analysis on YieldIQ`,
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
