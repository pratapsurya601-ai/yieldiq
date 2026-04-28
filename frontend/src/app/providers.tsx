"use client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useState, useEffect } from "react"
import InstallPrompt from "@/components/InstallPrompt"
import PaygHydrator from "@/components/payg/PaygHydrator"
import CookieAuthSync from "@/components/CookieAuthSync"

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 60 * 1000,
            retry: 2,
            // Default refetchOnWindowFocus=true fires a request every
            // time the user switches back to the tab. For a finance app
            // where most data (DCF, Prism, ratios) is slow-changing,
            // this burns bandwidth + rate-limits us against upstream
            // providers (yfinance, Groq) for no UX benefit — staleTime
            // already handles freshness. Opt out; individual queries
            // that DO need tab-focus refetch can override per-call.
            refetchOnWindowFocus: false,
          },
        },
      })
  )

  // Fire-and-forget ping to the API root on app mount. Wakes Railway's
  // backend container before the user navigates to /search or clicks
  // Analyse. Silent — no error handling, no blocking.
  useEffect(() => {
    const base =
      process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    fetch(`${base}/health`, { cache: "no-store" }).catch(() => {
      /* intentionally ignored — warmup is best-effort */
    })
  }, [])

  return (
    <QueryClientProvider client={queryClient}>
      {/* Mirrors the Zustand auth-store token into the `yieldiq_token`
          cookie with a sliding 30-day expiry. Without this, the cookie
          (set with a fixed 7-day expiry at login) silently drops while
          the persisted Zustand token survives — which made the SSR
          cookie check on /analysis/[ticker] render the anon signup
          wall to fully-paid users. Renders nothing. */}
      <CookieAuthSync />
      {/* Seeds usePaygStore from /payg-unlocks whenever the user is
          authed. Renders nothing; kept inside QueryClientProvider so it
          can piggy-back on react-query's retry / caching. */}
      <PaygHydrator />
      {children}
      <InstallPrompt />
    </QueryClientProvider>
  )
}
