"use client"
// PaygHydrator — fires once on mount (and when the auth token appears /
// changes) to seed the PAYG unlock store from the backend. Exposing this
// as a zero-render component keeps `providers.tsx` tidy: drop it anywhere
// inside the QueryClientProvider tree and forget about it.
//
// Backend already filters unlocks to the last 24 h, so whatever we get
// back is guaranteed fresh. We re-use react-query so the call benefits
// from the standard retry / stale-time policy without a custom fetcher.

import { useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { listPaygUnlocks } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { usePaygStore } from "@/store/paygStore"

export default function PaygHydrator() {
  const token = useAuthStore((s) => s.token)
  const setFromServer = usePaygStore((s) => s.setFromServer)
  const clear = usePaygStore((s) => s.clear)

  const { data } = useQuery({
    queryKey: ["payg-unlocks", token],
    queryFn: listPaygUnlocks,
    enabled: !!token,
    // Unlocks are 24 h-scoped — no reason to hammer this endpoint. 5 min
    // keeps the "hours remaining" badge fresh-ish if the user comes back
    // to a stale tab.
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  useEffect(() => {
    if (!token) {
      // Signed out → drop any cached unlocks so we don't leak them into
      // the next account that signs in on the same browser.
      clear()
      return
    }
    if (data?.unlocks) {
      setFromServer(data.unlocks)
    }
  }, [token, data, setFromServer, clear])

  return null
}
