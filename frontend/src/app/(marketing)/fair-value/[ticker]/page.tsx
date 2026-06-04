/**
 * /fair-value/[ticker] — programmatic SEO content page (server component).
 *
 * Built to test one hypothesis on a 4-week clock from Search-Console
 * submission: do these pages accumulate impressions for the
 * `[ticker] fair value` / `[ticker] intrinsic value` /
 * `[ticker] dcf analysis` query family for the 12 chosen NIFTY-50
 * large-caps. The one metric is Search Console impressions. The
 * decision criterion is post-window: meaningful impressions on
 * multiple tickers → extend content surface; negligible across all
 * tickers → SEO is not the channel, pivot.
 *
 * The page is a pure server component (no "use client") so the prose
 * and the JSON-LD ship in the SSR HTML stream Googlebot indexes. Data
 * comes from /api/v1/prism — the same endpoint /analysis/[ticker]
 * uses for its layout metadata, so Next.js's fetch-dedupe collapses
 * any downstream call on the same request.
 *
 * Tickers are bounded to the curated list in ./tickers.ts. Any other
 * URL segment returns 404 — programmatic content is only meaningful
 * for entries with hand-authored moat copy.
 */

import type { Metadata } from "next"
import { notFound } from "next/navigation"

import FairValueContent, {
  buildFaq,
  type FairValueViewModel,
} from "./FairValueContent"
import FairValueJsonLd from "./JsonLd"
import { FAIR_VALUE_TICKERS, findFairValueConfig } from "../tickers"

interface PrismSsrPayload {
  ticker?: string
  company_name?: string
  sector?: string | null
  price?: number | null
  fair_value?: number | null
  fair_value_bear?: number | null
  fair_value_bull?: number | null
  mos_pct?: number | null
  verdict_label?: string | null
  yieldiq_score_100?: number | null
  moat_label?: string | null
  piotroski_f_score?: number | null
  red_flag_count?: number | null
  wacc_pct?: number | null
  terminal_growth_pct?: number | null
  revenue_growth_pct?: number | null
}

// Re-fetch hourly. The DCF inputs do not change intra-day in any
// way that matters for SEO; bounding staleness at 60 minutes keeps
// the Vercel render budget low while still picking up the nightly
// recompute well before Googlebot's next crawl.
export const revalidate = 3600

// Pre-render all 12 ticker pages at build time so the first
// Googlebot crawl gets a fully rendered HTML response without
// waiting on the upstream API.
export function generateStaticParams() {
  return FAIR_VALUE_TICKERS.map((c) => ({ ticker: c.ticker }))
}

async function fetchPrism(ticker: string): Promise<PrismSsrPayload | null> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "https://api.yieldiq.in"
  try {
    const res = await fetch(`${apiUrl}/api/v1/prism/${ticker}`, {
      next: { revalidate: 3600 },
    })
    if (!res.ok) return null
    return (await res.json()) as PrismSsrPayload
  } catch {
    return null
  }
}

function formatUpdatedDate(): string {
  // Use a UTC-stable formatter so server vs. edge renders agree on
  // the exact string and Vercel's cache doesn't store two variants.
  const d = new Date()
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  })
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ ticker: string }>
}): Promise<Metadata> {
  const { ticker } = await params
  const config = findFairValueConfig(ticker)
  if (!config) {
    return { title: "Fair Value | YieldIQ" }
  }
  const title = `${config.companyName} (${config.displayTicker}) Fair Value | YieldIQ DCF`
  const description =
    `Independent DCF-based fair value for ${config.companyName} ` +
    `(${config.displayTicker}). See bear / base / bull scenarios and ` +
    `quality scores — updated daily.`
  const canonical = `https://yieldiq.in/fair-value/${config.ticker}`
  const ogImageUrl = `https://yieldiq.in/api/og/${config.ticker}`
  return {
    title,
    description,
    alternates: { canonical },
    openGraph: {
      title,
      description,
      url: canonical,
      siteName: "YieldIQ",
      type: "article",
      locale: "en_IN",
      images: [
        {
          url: ogImageUrl,
          width: 1200,
          height: 630,
          alt: `${config.companyName} fair value analysis on YieldIQ`,
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

export default async function FairValuePage({
  params,
}: {
  params: Promise<{ ticker: string }>
}) {
  const { ticker } = await params
  const config = findFairValueConfig(ticker)
  if (!config) {
    notFound()
  }

  const prism = await fetchPrism(config.ticker)
  const exchange: "NSE" | "BSE" = config.ticker.toUpperCase().endsWith(".BO")
    ? "BSE"
    : "NSE"

  // Fetch peer prism payloads in parallel so the comparison table
  // shows live numbers. Bounded to 3 peers per config, so this is
  // at most 4 upstream calls per render (1 + 3) — well within the
  // edge function budget on Vercel.
  const peerPayloads = await Promise.all(
    config.peers.slice(0, 3).map(async (peer) => {
      // Peer entries can be percent-encoded for sitemap URL safety
      // ("M%26M" → "M&M"). Decode before hitting the API.
      const decoded = decodeURIComponent(peer)
      const peerTicker = decoded.endsWith(".NS") ? decoded : `${decoded}.NS`
      const payload = await fetchPrism(peerTicker)
      return {
        ticker: decoded,
        companyName:
          (payload?.company_name && payload.company_name.trim()) || decoded,
        fairValue: payload?.fair_value ?? null,
        mosPct: payload?.mos_pct ?? null,
      }
    }),
  )

  const vm: FairValueViewModel = {
    ticker: config.ticker,
    displayTicker: config.displayTicker,
    companyName:
      (prism?.company_name && prism.company_name.trim()) || config.companyName,
    sector: prism?.sector ?? null,
    currentPrice: prism?.price ?? null,
    fairValue: prism?.fair_value ?? null,
    mosPct: prism?.mos_pct ?? null,
    yieldiqScore: prism?.yieldiq_score_100 ?? null,
    verdict: prism?.verdict_label ?? "",
    fairValueBear: prism?.fair_value_bear ?? null,
    fairValueBull: prism?.fair_value_bull ?? null,
    moatLabel: prism?.moat_label ?? null,
    fScore: prism?.piotroski_f_score ?? null,
    redFlagCount: prism?.red_flag_count ?? null,
    waccPct: prism?.wacc_pct ?? null,
    terminalGrowthPct: prism?.terminal_growth_pct ?? null,
    revenueGrowthPct: prism?.revenue_growth_pct ?? null,
    peers: peerPayloads.filter(
      (p) => p.fairValue !== null || p.mosPct !== null,
    ),
    moatPhrase: config.moatPhrase,
    updatedDate: formatUpdatedDate(),
  }

  const faq = buildFaq(vm)

  return (
    <>
      <FairValueJsonLd
        ticker={config.ticker}
        displayTicker={config.displayTicker}
        companyName={vm.companyName}
        sector={vm.sector}
        currentPrice={vm.currentPrice}
        fairValue={vm.fairValue}
        mosPct={vm.mosPct}
        yieldiqScore={vm.yieldiqScore}
        verdict={vm.verdict}
        exchange={exchange}
        faq={faq}
      />
      <FairValueContent vm={vm} />
    </>
  )
}
