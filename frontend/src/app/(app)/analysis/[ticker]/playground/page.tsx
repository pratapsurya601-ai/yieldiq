/**
 * /analysis/[ticker]/playground — Reverse-DCF Playground.
 *
 * The killer interactive feature from Design Manifesto v1 (Week 2).
 * Five sliders (WACC / Terminal Growth / Revenue CAGR / Operating
 * Margin / Tax Rate) drive a CLIENT-SIDE DCF recompute. On mount we
 * fetch two anchor recomputes from the backend so the JS DCF can be
 * calibrated to the analyst FV; every subsequent slider drag updates
 * the displayed FV with pure math, no network roundtrip.
 *
 * State is mirrored to the URL query string so users can share their
 * scenario. The body uses `useSearchParams`, which Next 16 requires
 * be wrapped in a Suspense boundary to avoid the prerender bailout
 * (see frontend/CLAUDE.md note on the /search-suspense pattern).
 *
 * Tier policy is rendered in the body (soft paywall on 4/5 sliders
 * for free tier). The endpoint itself is open — gating is UX, not
 * a security boundary.
 */
import { Suspense } from "react"
import PlaygroundBody from "./PlaygroundBody"

export const dynamic = "force-dynamic"

function PlaygroundFallback() {
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:py-12">
      <div className="mb-8">
        <p className="text-[11px] font-bold uppercase tracking-[0.25em] text-muted">
          DCF Playground
        </p>
        <div className="mt-2 h-8 w-64 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
        <div className="mt-2 h-4 w-96 max-w-full animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="h-96 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-900" />
        <div className="h-96 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-900" />
      </div>
    </div>
  )
}

export default async function PlaygroundPage({
  params,
}: {
  params: Promise<{ ticker: string }>
}) {
  const { ticker } = await params
  return (
    <Suspense fallback={<PlaygroundFallback />}>
      <PlaygroundBody ticker={ticker} />
    </Suspense>
  )
}
