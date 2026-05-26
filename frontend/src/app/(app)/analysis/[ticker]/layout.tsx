import type { Metadata } from "next"
import { verdictDisplayLabel } from "@/lib/utils"

interface Props {
  params: Promise<{ ticker: string }>
}

// Verdicts where the model could not produce a confident fair value.
// We must NEVER let the wire-format verdict ("data_limited",
// "unavailable") or its title-cased form ("Data Limited") leak into a
// page title or social-card preview — to a casual reader on Reddit /
// Twitter the phrase reads as "the app is broken" or "this stock is
// blacklisted", neither of which is true. Use neutral phrasing instead.
// Day-64 (2026-05-21): expanded to include "under_review" (top-level
// validator status) and "low_confidence" (Day-61 verdict-pill gate)
// so the page title never confidently advertises a verdict the body
// has already neutralised. HDFCBANK 2026-05-20 audit observed
// "HDFCBANK --- Undervalued | YieldIQ" in tab while the body
// rendered "Under Review" --- this set is the gate that fix lives in.
const UNDER_REVIEW_VERDICTS = new Set([
  "data_limited",
  "unavailable",
  "under_review",
  "low_confidence",
])

// Substrings that may appear in a backend-supplied title for an under-
// review ticker. Defense in depth: even if the og-data endpoint is
// later updated to emit new variants, the title sanitizer rejects any
// of these and falls back to the neutral form.
const FORBIDDEN_TITLE_SUBSTRINGS = [
  "Data Limited",
  "Unavailable",
  "Under Review",
  "Avoid",
  "Low Confidence",
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

  // Fetch OG data from API (description, status, og-image flags). The
  // canonical verdict label is sourced from /api/v1/prism/{ticker} below
  // so the tab title, anon hero badge, and Prism alt text all read from
  // the SAME backend field (`verdict_label`). Task #178 P0 (2026-05-24)
  // — three different verdict strings were rendering for HDFCBANK:
  //   • title  = "Notably Undervalued" (derived from MoS locally)
  //   • badge  = "UNDER REVIEW"        (PublicAnalysis confidence gate)
  //   • alt    = "Deep value region"   (backend verdict_label)
  // Day-34 "Verdict-chip consolidation — single source of truth"
  // missed the title + badge surfaces. Fix: every surface reads
  // verdict_label from /prism; local re-derivation is banned.
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://api.yieldiq.in"
  let ogData: Record<string, unknown> | null = null
  let prismData: Record<string, unknown> | null = null
  try {
    // Cache for 60s only — og-data title is derived from MoS, which is
    // recomputed by analysis_cache jobs throughout the day. A 1-hour
    // revalidate window meant a ticker that flipped from MoS=null →
    // MoS=+55.9% (INFY 2026-04-30) was stuck rendering the neutral
    // "Stock Analysis" tab title for up to an hour after the cache
    // recompute. 60s keeps SSR responsive without hammering the API.
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
  // Day-64 (2026-05-21): also gate on the top-level `status` field.
  // The public endpoint returns `{ status: "under_review", ... }` for
  // tickers the validator quarantined (ITCHOTELS / ABLBL pattern) ---
  // verdict may still carry a stale value in that payload.
  const backendStatus =
    typeof ogData?.status === "string" ? (ogData.status as string) : ""
  const prismVerdictLabelRaw =
    typeof prismData?.verdict_label === "string"
      ? (prismData.verdict_label as string)
      : ""
  const isUnderReview =
    UNDER_REVIEW_VERDICTS.has(verdict) ||
    UNDER_REVIEW_VERDICTS.has(backendStatus) ||
    FORBIDDEN_TITLE_SUBSTRINGS.some((s) => backendTitle.includes(s)) ||
    // Task #178: also gate when /prism returned an under-review label —
    // the canonical verdict_label can carry "Under Review" / "Insufficient
    // Data" / etc., and now that we render it verbatim in the title we
    // must not let those leak past the neutralizer.
    FORBIDDEN_TITLE_SUBSTRINGS.some((s) => prismVerdictLabelRaw.includes(s))

  // Task #178 (2026-05-24): canonical verdict label comes from the
  // /prism endpoint's `verdict_label` field — the SAME field the anon
  // hero badge and Prism alt text now read from. Local MoS-derivation
  // is banned; it produced the HDFCBANK three-strings-for-one-stock
  // P0 ("Notably Undervalued" in tab title, "UNDER REVIEW" in badge,
  // "Deep value region" in alt). When prism is unreachable, fall back
  // to mapping the og-data `verdict` enum through verdictDisplayLabel
  // — still a label-map, never a local re-derivation from mos/score.
  const prismVerdictLabel =
    typeof prismData?.verdict_label === "string" &&
    (prismData.verdict_label as string).trim().length > 0
      ? (prismData.verdict_label as string)
      : verdict
        ? verdictDisplayLabel(verdict)
        : ""
  // Always rebuild from displayTicker (which has .NS / .BO stripped) so
  // the tab title is clean even for tickers in a degraded data state.
  const title = isUnderReview
    ? neutralTitle(displayTicker)
    : prismVerdictLabel
      ? `${displayTicker} — ${prismVerdictLabel} | YieldIQ`
      : `${displayTicker} — Stock Analysis | YieldIQ`

  const description = isUnderReview
    ? neutralDescription(displayTicker)
    : backendDescription ||
      `Free DCF valuation for ${displayTicker}. See its fair-value estimate, margin of safety, and quality scores.`

  // Phase 4.2 (2026-05-25): Money Camera is now the canonical share
  // image. Same 1200x630 dimensions as the legacy /api/og/[ticker]
  // route, so no crawler-side breakage — Open Graph / Twitter / Slack
  // / WhatsApp all keep the same large_summary card geometry. The
  // older route is retained for backward compatibility with already-
  // scraped URLs in caches we don't control.
  const ogImageUrl = `https://yieldiq.in/api/og/money-camera/${ticker}?format=horizontal`

  // Stale-snippet defense: when the og-data endpoint reports a degraded
  // state (verdict in the under-review family OR an explicit
  // `data_limited` flag), tell crawlers not to index/follow this URL.
  // Otherwise Google holds onto the previous snippet for days after a
  // ticker flips into "Under Review" and users land on a degraded page
  // from search with no warning.
  const dataLimitedFlag =
    typeof ogData?.data_limited === "boolean" ? (ogData.data_limited as boolean) : false
  const noindex = isUnderReview || dataLimitedFlag

  return {
    title,
    description,
    robots: noindex ? { index: false, follow: false } : undefined,
    // Day-41 (2026-05-20): canonical URL prevents Google from
    // indexing URL variants (?utm_source=foo, ?ref=bar) as separate
    // pages. Always points at the bare /analysis/{ticker} URL.
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
          alt: `${displayTicker} stock analysis on YieldIQ`,
          // Day-42 (2026-05-20): og:image:type for older scrapers
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
