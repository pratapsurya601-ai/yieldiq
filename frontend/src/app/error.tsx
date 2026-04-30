"use client"
import * as Sentry from "@sentry/nextjs"
import { useEffect } from "react"

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }, reset: () => void }) {
  useEffect(() => {
    Sentry.captureException(error)
  }, [error])

  return (
    <div style={{ padding: "2rem", textAlign: "center", fontFamily: "system-ui" }}>
      <h2>Something went wrong</h2>
      <p style={{ color: "#666" }}>The error has been logged. Try again or refresh the page.</p>
      <button onClick={reset} style={{ marginTop: "1rem", padding: "0.5rem 1rem" }}>Try again</button>
    </div>
  )
}
