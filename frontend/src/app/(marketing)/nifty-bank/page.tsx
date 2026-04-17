import type { Metadata } from "next"
import IndexDashboardClient from "../nifty50/IndexDashboardClient"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export const metadata: Metadata = {
  title: "Nifty Bank Fair Value Dashboard \u2014 Banking Stocks Valued by DCF | YieldIQ",
  description: "Free DCF valuation of Nifty Bank stocks. HDFC Bank, ICICI Bank, SBI, Kotak, Axis Bank and more. Updated daily.",
  openGraph: {
    title: "Nifty Bank Valuation Dashboard | YieldIQ",
    description: "All Nifty Bank stocks ranked by DCF fair value. Free, updated daily.",
    url: "https://yieldiq.in/nifty-bank",
  },
  alternates: { canonical: "https://yieldiq.in/nifty-bank" },
}

export default async function NiftyBankPage() {
  let data = null
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/index-dashboard/nifty-bank`, {
      next: { revalidate: 900 },
    })
    if (res.ok) data = await res.json()
  } catch {}

  if (!data) {
    data = {
      index_id: "nifty-bank", index_name: "Nifty Bank Valuation Dashboard",
      description: "All Nifty Bank stocks ranked by DCF fair value",
      total_stocks: 12, available_stocks: 0, stocks: [],
      summary: { undervalued: 0, fairly_valued: 0, overvalued: 0, most_undervalued: null, most_overvalued: null },
    }
  }

  return <IndexDashboardClient data={data} />
}
