"use client"
import { useEffect } from "react"
import { registerServiceWorker } from "@/lib/registerSW"

// Minimal client shim that registers the service worker on first mount.
// Rendered once from the root layout — no DOM output.
export default function ServiceWorkerRegister() {
  useEffect(() => {
    registerServiceWorker()
  }, [])
  return null
}
