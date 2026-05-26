import type { Metadata } from "next"

// Even though /watchlist redirects to /portfolio?tab=watchlist, we set a
// distinct title so any browser tab that briefly lands here before the
// redirect resolves still announces the right page.
export const metadata: Metadata = {
  title: "Watchlist — YieldIQ",
}

export default function WatchlistLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
