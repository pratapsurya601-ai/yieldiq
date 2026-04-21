"use client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useState, useEffect } from "react"
import InstallPrompt from "@/components/InstallPrompt"
import PaygHydrator from "@/components/payg/PaygHydrator"

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 5 * 60 * 1000, retry: 2 },
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
      {/* Seeds usePaygStore from /payg-unlocks whenever the user is
          authed. Renders nothing; kept inside QueryClientProvider so it
          can piggy-back on react-query's retry / caching. */}
      <PaygHydrator />
      {children}
      <InstallPrompt />
    </QueryClientProvider>
  )
}
