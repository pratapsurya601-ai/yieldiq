// Register the YieldIQ service worker. Call this from a Client Component
// mount effect in the root layout. The SW is an optimization (SWR cache for
// public API routes) — all failure modes are silent.
//
// Notes:
//   - Dev-mode skip: Next.js HMR and the SW cache fight each other; only
//     register in production builds.
//   - iOS Safari has partial SW support; the feature-detect below handles it.
//   - We wait for window 'load' to avoid competing with first-paint work.
export function registerServiceWorker() {
  if (typeof window === "undefined") return
  if (!("serviceWorker" in navigator)) return
  if (process.env.NODE_ENV !== "production") return

  const register = () => {
    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .catch(() => {
        // Silent: the page still works without the SW.
      })
  }

  if (document.readyState === "complete") {
    register()
  } else {
    window.addEventListener("load", register, { once: true })
  }
}
