import type { Metadata } from "next"

interface Props {
  params: Promise<{ ticker: string }>
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

  const title =
    (ogData?.title as string) || `${displayTicker} Stock Analysis | YieldIQ`
  const description =
    (ogData?.description as string) ||
    `Free DCF valuation for ${displayTicker}. Know if it's undervalued.`

  return {
    title,
    description,
    openGraph: {
      title,
      description,
      url: `https://yieldiq.in/analysis/${ticker}`,
      siteName: "YieldIQ",
      type: "website",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
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
