import type { Metadata } from "next"

interface Props {
  params: Promise<{ ticker: string }>
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { ticker } = await params
  const displayTicker = ticker.replace(".NS", "").replace(".BO", "")

  return {
    title: `${displayTicker} Stock Analysis | YieldIQ`,
    description: `Free DCF valuation for ${displayTicker}. See fair value, YieldIQ Score, Piotroski F-Score, moat analysis, and scenario forecasts.`,
    openGraph: {
      title: `${displayTicker} Stock Analysis | YieldIQ`,
      description: `Free DCF valuation for ${displayTicker}. Know if it's undervalued.`,
      url: `https://yieldiq.in/analysis/${ticker}`,
      siteName: "YieldIQ",
      type: "website",
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
