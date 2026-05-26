import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Screener — YieldIQ",
}

export default function ScreenerLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
