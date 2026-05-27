/**
 * Layout + generateMetadata for /funds/[scheme_code].
 *
 * SEBI title-leak posture (mirrors the 2026-05-26 fix on /analysis):
 *   - NO verdict / advisory vocabulary anywhere in <title>, description,
 *     OG, or Twitter tags.
 *   - Title format:   "<Scheme name> — Mutual Fund Analysis | YieldIQ"
 *   - Description:    "<Scheme name> by <AMC>. NAV history, returns
 *                      vs benchmark, risk metrics."
 *
 * Falls back to scheme-code-only when the backend lookup fails — the
 * metadata pass must never throw, otherwise the page itself fails to
 * pre-render.
 */
import type { Metadata } from "next"

interface Props {
  params: Promise<{ scheme_code: string }>
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.yieldiq.in"

async function fetchFund(
  scheme_code: string,
): Promise<{ scheme_name: string; amc: string } | null> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/funds/${encodeURIComponent(scheme_code)}`,
      { next: { revalidate: 300 } },
    )
    if (!res.ok) return null
    const body = await res.json()
    const fund = body?.fund
    if (!fund || typeof fund.scheme_name !== "string") return null
    return {
      scheme_name: fund.scheme_name,
      amc: typeof fund.amc === "string" ? fund.amc : "",
    }
  } catch {
    return null
  }
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { scheme_code } = await params
  const fund = await fetchFund(scheme_code)

  const schemeName = fund?.scheme_name || `Scheme ${scheme_code}`
  const amc = fund?.amc || ""

  const title = `${schemeName} — Mutual Fund Analysis | YieldIQ`
  const description = amc
    ? `${schemeName} by ${amc}. NAV history, returns vs benchmark, risk metrics.`
    : `${schemeName}. NAV history, returns vs benchmark, risk metrics.`

  const canonical = `https://yieldiq.in/funds/${encodeURIComponent(scheme_code)}`

  return {
    title,
    description,
    alternates: { canonical },
    openGraph: {
      title,
      description,
      url: canonical,
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

export default function FundLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <>{children}</>
}
