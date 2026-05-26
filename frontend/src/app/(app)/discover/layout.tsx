import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Discover — YieldIQ",
}

export default function DiscoverLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
