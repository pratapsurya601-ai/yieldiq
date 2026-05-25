/**
 * /analysis/[ticker]/playground — Reverse-DCF Playground.
 *
 * The killer interactive feature from Design Manifesto v1 (Week 2).
 * Five sliders (WACC / Terminal Growth / Revenue CAGR / Operating
 * Margin / Tax Rate) drive a live DCF recompute, with a bear/bull
 * fan-out band and an "adopt the market-implied assumptions" panel
 * underneath.
 *
 * Server shell + client body — the body owns all of the slider
 * state, debounce, and POST calls. The shell is here so Next.js
 * generates a stable URL the user can deep-link to with their
 * favourite assumptions encoded in query params (future work).
 *
 * Tier policy is rendered in the body (soft paywall on 4/5 sliders
 * for free tier). The endpoint itself is open — gating is UX, not
 * a security boundary.
 */
import PlaygroundBody from "./PlaygroundBody"

export const dynamic = "force-dynamic"

export default async function PlaygroundPage({
  params,
}: {
  params: Promise<{ ticker: string }>
}) {
  const { ticker } = await params
  return <PlaygroundBody ticker={ticker} />
}
