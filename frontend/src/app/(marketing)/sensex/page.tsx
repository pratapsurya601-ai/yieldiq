// /sensex — Sensex valuation dashboard.
//
// 2026-06-09 (Bug 3): MarketsStrip's SENSEX tile was previously a
// static div because INDEX_ROUTES had no entry for it. This page
// mirrors the /nifty-bank and /nifty-it pattern verbatim — fetch
// the public index-dashboard endpoint, then render with the shared
// IndexDashboardClient. The backend serves the 30-stock BSE
// constituent list under slug ``sensex`` (see INDICES in
// backend/routers/public.py).

import type { Metadata } from "next"
import IndexDashboardClient from "../nifty50/IndexDashboardClient"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export const metadata: Metadata = {
  title: "Sensex Fair Value Dashboard — 30 BSE Stocks Valued by DCF | YieldIQ",
  description:
    "Free DCF valuation of all 30 Sensex stocks. Reliance, TCS, HDFC Bank, Infosys, ITC and more. Updated daily.",
  openGraph: {
    title: "Sensex Valuation Dashboard | YieldIQ",
    description: "All 30 Sensex stocks ranked by DCF fair value. Free, updated daily.",
    url: "https://yieldiq.in/sensex",
    siteName: "YieldIQ",
    type: "website",
    images: [{ url: "https://yieldiq.in/logo_icon.jpeg", width: 512, height: 512 }],
  },
  alternates: { canonical: "https://yieldiq.in/sensex" },
}

export default async function SensexPage() {
  let data = null
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/index-dashboard/sensex`, {
      next: { revalidate: 900 },
    })
    if (res.ok) data = await res.json()
  } catch {}

  if (!data) {
    data = {
      index_id: "sensex",
      index_name: "Sensex Valuation Dashboard",
      description: "All 30 Sensex stocks ranked by DCF fair value",
      total_stocks: 30,
      available_stocks: 0,
      stocks: [],
      summary: {
        undervalued: 0,
        fairly_valued: 0,
        overvalued: 0,
        most_undervalued: null,
        most_overvalued: null,
      },
    }
  }

  return <IndexDashboardClient data={data} />
}
