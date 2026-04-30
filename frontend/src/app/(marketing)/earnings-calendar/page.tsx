import type { Metadata } from "next"
import EarningsCalendarClient from "./EarningsCalendarClient"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export const metadata: Metadata = {
  title: "Indian Stock Earnings Calendar — Upcoming Q Results | YieldIQ",
  description: "Free earnings calendar for NSE/BSE stocks. See upcoming quarterly results, AGMs, and corporate announcements. Updated daily from NSE.",
  openGraph: {
    title: "Earnings Calendar — Indian Stocks | YieldIQ",
    description: "Track upcoming quarterly results for 2,300+ Indian stocks. Free, no signup required.",
    url: "https://yieldiq.in/earnings-calendar",
  },
  alternates: { canonical: "https://yieldiq.in/earnings-calendar" },
}

export default async function EarningsCalendarPage() {
  let data = null
  try {
    // Window matches what we actually render below (next 7 days).
    // Previously requested 14 but the page only showed 7, leaving the
    // header copy "next 14 days" out of sync with the UI.
    const res = await fetch(`${API_BASE}/api/v1/public/earnings-calendar?days=7&limit=200`, {
      next: { revalidate: 3600 },
    })
    if (res.ok) data = await res.json()
  } catch {}

  if (!data) {
    data = { total: 0, window_days: 7, by_date: [], events: [] }
  }

  return <EarningsCalendarClient data={data} />
}
