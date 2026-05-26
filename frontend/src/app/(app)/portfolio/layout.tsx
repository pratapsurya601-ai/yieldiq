import type { Metadata } from "next"

// Per-route metadata override (audit 2026-05-26 P1). The app-level
// default title was leaking onto every workspace route, leaving five
// browser tabs all reading the same string. Each route now exports
// its own title via a server-component layout so the client page can
// stay a "use client" module.
export const metadata: Metadata = {
  title: "Portfolio — YieldIQ",
}

export default function PortfolioLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
