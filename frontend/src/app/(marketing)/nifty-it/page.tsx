import type { Metadata } from "next"
import IndexDashboardClient from "../nifty50/IndexDashboardClient"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export const metadata: Metadata = {
  title: "Nifty IT Fair Value Dashboard \u2014 IT Stocks Valued by DCF | YieldIQ",
  description: "Free DCF valuation of Nifty IT stocks. TCS, Infosys, Wipro, HCL Tech, Tech Mahindra and more. Updated daily.",
  openGraph: {
    title: "Nifty IT Valuation Dashboard | YieldIQ",
    description: "All Nifty IT stocks ranked by DCF fair value. Free, updated daily.",
    url: "https://yieldiq.in/nifty-it",
  },
  alternates: { canonical: "https://yieldiq.in/nifty-it" },
}

export default async function NiftyITPage() {
  let data = null
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/index-dashboard/nifty-it`, {
      next: { revalidate: 900 },
    })
    if (res.ok) data = await res.json()
  } catch {}

  if (!data) {
    data = {
      index_id: "nifty-it", index_name: "Nifty IT Valuation Dashboard",
      description: "All Nifty IT stocks ranked by DCF fair value",
      total_stocks: 10, available_stocks: 0, stocks: [],
      summary: { undervalued: 0, fairly_valued: 0, overvalued: 0, most_undervalued: null, most_overvalued: null },
    }
  }

  return <IndexDashboardClient data={data} />
}
