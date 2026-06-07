import { ImageResponse } from "next/og"
import type { NextRequest } from "next/server"
import { fetchCompanyLogoDataUrl } from "../../_lib/companyLogo"

/**
 * Money Camera — single-frame, scroll-stopping share artefact.
 *
 * Phase 4.2 (2026-05-25). Third parallel OG route. Coexists with the
 * older horizontal preview (`/api/og/[ticker]`) and the portrait Share
 * Report Card (`/api/og/analysis/[ticker]`). NEITHER of those is
 * modified. Eventual consolidation is a separate cleanup task.
 *
 * Two formats sized for the dominant share surfaces:
 *   ?format=horizontal  → 1200x630   (Open Graph, Twitter/X, LinkedIn)
 *   ?format=story       → 1080x1920  (Instagram Story / WhatsApp Status)
 *
 * The visible content reads as a one-glance summary:
 *
 *   TICKER · Company name
 *   ₹FV  fair value
 *   ₹MP  market price
 *   ✓ X% below fair value
 *   [tiny fan-out chart — bear / base / bull as SVG <path>s]
 *   "<prism narrative caption>"
 *   yieldiq.in/analysis/TICKER
 *   [192px SEBI compliance banner — baked in]
 *
 * Satori SVG constraint: the bundled Satori rejects <text> nodes. The
 * fan-out is therefore drawn purely with <path> elements; ₹-labels for
 * the three scenarios are layered as absolutely-positioned HTML divs
 * (same trick the analysis/Prism-hex route uses).
 *
 * SEBI vocabulary: the visible card text avoids every banned verb and
 * adjective in scripts/check_sebi_words.py (the imperative/affective
 * list). The verdict reads "below fair value" / "near fair value" /
 * "above fair value" — the same neutral phrasing the horizontal
 * Open-Graph route already uses.
 */

export const runtime = "edge"
// Aligns with the existing OG cache headers — 1h edge revalidate so a
// thesis update lands on the share surface within an hour at most.
export const revalidate = 3600

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.yieldiq.in"

// ─── Types (inlined — Satori edge bundles dislike cross-imports) ─────
interface StockSummary {
  ticker?: string
  company_name?: string
  sector?: string
  fair_value?: number
  current_price?: number
  mos?: number
  mos_pct?: number
  verdict?: string
  bear_case?: number
  base_case?: number
  bull_case?: number
  prism_narrative?: string
  one_liner?: string
}

function fmtINR(n: number | undefined | null): string {
  if (n == null || !Number.isFinite(n) || n <= 0) return "—"
  // Satori edge bundle dislikes cross-imports; mirrors the inline
  // pattern used by the sibling /api/og/[ticker] and
  // /api/og/analysis/[ticker] routes.
  // eslint-disable-next-line no-restricted-syntax
  return `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
}

function truncate(s: string, n: number): string {
  if (!s) return ""
  return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s
}

// SEBI-safe verdict caption. Mirrors the horizontal route's
// `verdictLabel` phrasing but adds the MoS magnitude when meaningful.
function verdictCaption(v: string | undefined, mosPct: number): string {
  const abs = Math.abs(mosPct)
  const pretty = abs.toFixed(0)
  switch (v) {
    case "undervalued":
      return `✓ ${pretty}% below fair value`
    case "fairly_valued":
      return "Near fair value"
    case "overvalued":
      return `${pretty}% above fair value`
    case "avoid":
      return "High risk"
    case "data_limited":
    case "unavailable":
    default:
      return "Under review"
  }
}

// Verdict gradient cascade. Mirrors src/lib/verdict-colors.ts but in
// raw CSS gradients (Satori does not run Tailwind). Emerald→teal for
// undervalued, slate-to-stone for fair, rust-to-orange for overvalued.
function verdictGradient(v: string | undefined): string {
  switch (v) {
    case "undervalued":
      // emerald-700 → teal-800 with a deep slate base for legibility
      return "linear-gradient(135deg, #064E3B 0%, #0F766E 50%, #0B1220 100%)"
    case "fairly_valued":
      // slate-600 → stone-800 — calm, no signal
      return "linear-gradient(135deg, #334155 0%, #44403C 60%, #0B1220 100%)"
    case "overvalued":
      // rust → orange-900 — warm caution, never red-alarm
      return "linear-gradient(135deg, #7C2D12 0%, #9A3412 55%, #0B1220 100%)"
    case "avoid":
      return "linear-gradient(135deg, #7F1D1D 0%, #991B1B 55%, #0B1220 100%)"
    default:
      // data_limited / under_review — washed-out, intentional "we're
      // not sure" tone (mirrors the data_limited VerdictTier token).
      return "linear-gradient(135deg, #475569 0%, #334155 55%, #0B1220 100%)"
  }
}

function verdictAccent(v: string | undefined): string {
  switch (v) {
    case "undervalued":
      return "#10B981"
    case "fairly_valued":
      return "#94A3B8"
    case "overvalued":
      return "#F59E0B"
    case "avoid":
      return "#EF4444"
    default:
      return "#64748B"
  }
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params
  const url = new URL(request.url)
  const format = (url.searchParams.get("format") || "horizontal").toLowerCase()
  const isStory = format === "story"

  const tickerUpper = (ticker || "").toUpperCase()
  const cleanTicker = tickerUpper.replace(/\.(NS|BO)$/i, "")
  const fullTicker = tickerUpper.includes(".") ? tickerUpper : `${tickerUpper}.NS`

  // Single upstream fetch — all surface fields live on the public
  // stock-summary payload (per Phase 4.2 decision (e): no new backend
  // endpoint). 8s timeout matches the analysis OG route.
  let summary: StockSummary = {}
  // Parallel: summary + Clearbit logo. Logo helper has 2s timeout and
  // never throws; null falls back to no-logo (just ticker text).
  const [summaryResult, logoDataUrl] = await Promise.all([
    (async () => {
      try {
        const res = await fetch(
          `${API_BASE}/api/v1/public/stock-summary/${encodeURIComponent(fullTicker)}`,
          { signal: AbortSignal.timeout(8000) }
        )
        if (res.ok) {
          return (await res.json()) as StockSummary
        }
      } catch {
        // Fall through — "Under review" layout below absorbs the failure.
      }
      return {} as StockSummary
    })(),
    fetchCompanyLogoDataUrl(cleanTicker),
  ])
  summary = summaryResult

  const fairValue = Number(summary.fair_value ?? 0)
  const price = Number(summary.current_price ?? 0)
  // mos_pct is the canonical field; mos is the legacy alias.
  const mosPct = Number(
    summary.mos_pct ?? summary.mos ?? 0
  )
  const verdict = (summary.verdict || "data_limited").toString()
  const bear = Number(summary.bear_case ?? 0)
  const base = Number(summary.base_case ?? fairValue)
  const bull = Number(summary.bull_case ?? 0)

  const companyName = truncate(
    summary.company_name || cleanTicker,
    isStory ? 32 : 38
  )
  const narrative = truncate(
    (summary.prism_narrative || summary.one_liner || "").toString(),
    isStory ? 60 : 56
  )

  const isUnderReview =
    verdict === "data_limited" ||
    verdict === "unavailable" ||
    !fairValue ||
    fairValue <= 0

  const gradient = verdictGradient(isUnderReview ? "data_limited" : verdict)
  const accent = verdictAccent(isUnderReview ? "data_limited" : verdict)
  const caption = verdictCaption(verdict, mosPct)

  // ─── Layout dimensions ────────────────────────────────────────────
  // 192px SEBI banner reserved at the bottom of BOTH formats per Phase
  // 4.2 decision (c). The disclaimer is baked into the rasterised PNG,
  // not a DOM overlay — matches the FIX-SEBI-COMPLIANCE pattern from
  // the portrait Share Report Card route.
  const W = isStory ? 1080 : 1200
  const H = isStory ? 1920 : 630
  const SEBI_H = 192
  const CONTENT_PAD_X = isStory ? 72 : 64
  const CONTENT_PAD_TOP = isStory ? 96 : 56

  // Fan-out chart geometry. Three SVG <path>s — one per scenario,
  // ramping from "today" on the left to the scenario FV on the right.
  // Bear under base under bull. Pure paths; numeric ₹-labels are HTML
  // overlays positioned by absolute pixel.
  const CHART_W = isStory ? 880 : 360
  const CHART_H = isStory ? 220 : 120
  // Normalise the three scenarios into [0, 1] for the chart Y. Treat
  // the data range as bear..bull with a small padding so the bear path
  // never sits flush against the bottom edge.
  const vals = [bear || base * 0.7, base, bull || base * 1.3].map((v) =>
    Number.isFinite(v) && v > 0 ? v : 0
  )
  const vMin = Math.min(...vals)
  const vMax = Math.max(...vals)
  const vRange = Math.max(1, vMax - vMin)
  const yOf = (v: number): number => {
    const norm = (v - vMin) / vRange  // 0 (bottom) .. 1 (top)
    const pad = 0.12
    return CHART_H - (pad + norm * (1 - 2 * pad)) * CHART_H
  }
  const x0 = 0
  const xEnd = CHART_W
  // Pick a single "today" y-anchor on the left so all three rays
  // emanate from the same starting price.
  const yToday = CHART_H * 0.62
  const pathFor = (v: number): string => {
    const y2 = yOf(v)
    // Cubic curve for a soft fan-out.
    const cx1 = x0 + (xEnd - x0) * 0.45
    const cy1 = yToday
    const cx2 = xEnd - (xEnd - x0) * 0.25
    const cy2 = y2
    return `M ${x0} ${yToday} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${xEnd} ${y2}`
  }
  const bearPath = pathFor(vals[0])
  const basePath = pathFor(vals[1])
  const bullPath = pathFor(vals[2])
  const hasChart = !isUnderReview && vals.every((v) => v > 0) && vMax > vMin

  // ─── Common JSX helpers ──────────────────────────────────────────
  // Logo plate sizes are format-specific: story-format ticker is much
  // larger so the logo scales with it; horizontal stays compact.
  const logoPlateSize = isStory ? 120 : 80
  const logoImgSize = isStory ? 96 : 64
  const logoRadius = isStory ? 24 : 16

  const tickerBlock = (
    <div style={{ display: "flex", flexDirection: "column", lineHeight: 1 }}>
      <div style={{ display: "flex", alignItems: "center", gap: isStory ? 24 : 18 }}>
        {logoDataUrl ? (
          /* Company logo (Clearbit, server-fetched). White plate so
             transparent SVG/PNG logos read against the dark background. */
          <div
            style={{
              width: logoPlateSize,
              height: logoPlateSize,
              borderRadius: logoRadius,
              background: "#FFFFFF",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
              padding: isStory ? 12 : 8,
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={logoDataUrl}
              width={logoImgSize}
              height={logoImgSize}
              alt=""
              style={{ objectFit: "contain" }}
            />
          </div>
        ) : null}
        <div
          style={{
            color: "#FFFFFF",
            fontSize: isStory ? 120 : 72,
            fontWeight: 900,
            letterSpacing: -3,
            display: "flex",
          }}
        >
          {cleanTicker}
        </div>
      </div>
      <div
        style={{
          color: "#CBD5E1",
          fontSize: isStory ? 32 : 24,
          fontWeight: 500,
          marginTop: 14,
          display: "flex",
        }}
      >
        {companyName}
      </div>
    </div>
  )

  const wordmark = (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <div
        style={{
          width: isStory ? 56 : 44,
          height: isStory ? 56 : 44,
          borderRadius: 12,
          background: "linear-gradient(135deg, #3B82F6, #06B6D4)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "white",
          fontSize: isStory ? 32 : 26,
          fontWeight: 900,
        }}
      >
        Y
      </div>
      <div
        style={{
          fontSize: isStory ? 36 : 28,
          fontWeight: 900,
          letterSpacing: -1,
          display: "flex",
          lineHeight: 1,
        }}
      >
        <span style={{ color: "#60A5FA" }}>Yield</span>
        <span style={{ color: "#FFFFFF" }}>IQ</span>
      </div>
    </div>
  )

  const fvPriceRows = (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: isStory ? 22 : 14,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 18 }}>
        <div
          style={{
            color: "#FFFFFF",
            fontSize: isStory ? 96 : 60,
            fontWeight: 900,
            lineHeight: 1,
            display: "flex",
          }}
        >
          {isUnderReview ? "—" : fmtINR(fairValue)}
        </div>
        <div
          style={{
            color: "#94A3B8",
            fontSize: isStory ? 28 : 20,
            fontWeight: 600,
            letterSpacing: 2,
            textTransform: "uppercase",
            display: "flex",
          }}
        >
          fair value
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 18 }}>
        <div
          style={{
            color: "#CBD5E1",
            fontSize: isStory ? 72 : 44,
            fontWeight: 800,
            lineHeight: 1,
            display: "flex",
          }}
        >
          {fmtINR(price)}
        </div>
        <div
          style={{
            color: "#94A3B8",
            fontSize: isStory ? 28 : 20,
            fontWeight: 600,
            letterSpacing: 2,
            textTransform: "uppercase",
            display: "flex",
          }}
        >
          market price
        </div>
      </div>
    </div>
  )

  const verdictPill = (
    <div style={{ display: "flex" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: isStory ? "16px 32px" : "10px 22px",
          background: `${accent}22`,
          border: `2px solid ${accent}`,
          borderRadius: 999,
          color: accent,
          fontSize: isStory ? 36 : 26,
          fontWeight: 800,
          letterSpacing: 0.5,
        }}
      >
        {caption}
      </div>
    </div>
  )

  const narrativeBlock = narrative ? (
    <div
      style={{
        color: "#E2E8F0",
        fontSize: isStory ? 30 : 22,
        fontWeight: 500,
        fontStyle: "italic",
        display: "flex",
        lineHeight: 1.3,
      }}
    >
      {`“${narrative}”`}
    </div>
  ) : null

  const cta = (
    <div
      style={{
        color: "#60A5FA",
        fontSize: isStory ? 30 : 22,
        fontWeight: 700,
        letterSpacing: 0.5,
        display: "flex",
      }}
    >
      {`yieldiq.in/analysis/${cleanTicker}`}
    </div>
  )

  // Fan-out chart. SVG paths only; labels overlaid as HTML divs at the
  // right edge. Positioned with absolute coords so the parent flex
  // doesn't need to measure the SVG.
  const chartLabelStyle = (color: string, top: number, left: number) => ({
    position: "absolute" as const,
    left,
    top,
    color,
    fontSize: isStory ? 22 : 14,
    fontWeight: 800,
    letterSpacing: 0.5,
    display: "flex",
  })

  const chartBlock = hasChart ? (
    <div
      style={{
        position: "relative",
        width: CHART_W,
        height: CHART_H,
        display: "flex",
      }}
    >
      <svg width={CHART_W} height={CHART_H}>
        <defs>
          <linearGradient id="mc-bear" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#F87171" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#F87171" stopOpacity="1" />
          </linearGradient>
          <linearGradient id="mc-base" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#60A5FA" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#60A5FA" stopOpacity="1" />
          </linearGradient>
          <linearGradient id="mc-bull" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#34D399" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#34D399" stopOpacity="1" />
          </linearGradient>
        </defs>
        {/* "Today" anchor dot */}
        <circle cx={x0 + 4} cy={yToday} r={6} fill="#E2E8F0" />
        <path d={bearPath} stroke="url(#mc-bear)" strokeWidth={4} fill="none" strokeLinecap="round" />
        <path d={basePath} stroke="url(#mc-base)" strokeWidth={5} fill="none" strokeLinecap="round" />
        <path d={bullPath} stroke="url(#mc-bull)" strokeWidth={4} fill="none" strokeLinecap="round" />
        {/* End-point dots */}
        <circle cx={xEnd} cy={yOf(vals[0])} r={6} fill="#F87171" />
        <circle cx={xEnd} cy={yOf(vals[1])} r={7} fill="#60A5FA" />
        <circle cx={xEnd} cy={yOf(vals[2])} r={6} fill="#34D399" />
      </svg>
      {/* Scenario value labels — HTML overlays (Satori rejects <text>).
          Offsets put them just to the left of the end-point dots. */}
      <div style={chartLabelStyle("#34D399", Math.max(0, yOf(vals[2]) - (isStory ? 28 : 18)), Math.max(0, xEnd - (isStory ? 160 : 100)))}>
        Bull {fmtINR(vals[2])}
      </div>
      <div style={chartLabelStyle("#60A5FA", Math.max(0, yOf(vals[1]) - (isStory ? 14 : 8)), Math.max(0, xEnd - (isStory ? 160 : 100)))}>
        Base {fmtINR(vals[1])}
      </div>
      <div style={chartLabelStyle("#F87171", Math.min(CHART_H - 28, yOf(vals[0]) + (isStory ? 4 : 2)), Math.max(0, xEnd - (isStory ? 160 : 100)))}>
        Bear {fmtINR(vals[0])}
      </div>
    </div>
  ) : null

  const sebiBanner = (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 0,
        height: SEBI_H,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "0 48px",
        background: "#78350F",
        borderTop: "4px solid #F59E0B",
      }}
    >
      <div
        style={{
          color: "#FDE68A",
          fontSize: isStory ? 22 : 18,
          fontWeight: 800,
          letterSpacing: 3,
          textTransform: "uppercase",
          display: "flex",
          marginBottom: 12,
        }}
      >
        Important Disclosure
      </div>
      <div
        style={{
          color: "#FFFFFF",
          fontSize: isStory ? 28 : 22,
          fontWeight: 700,
          textAlign: "center",
          lineHeight: 1.3,
          display: "flex",
        }}
      >
        {"Model estimate · Not investment advice · YieldIQ is not SEBI-registered"}
      </div>
    </div>
  )

  // ─── Compose ────────────────────────────────────────────────────
  // The story format stacks vertically with extra breathing room; the
  // horizontal format uses a 2-column layout with the fan-out chart
  // on the right of the FV/price block.
  const root = isStory ? (
    <div
      style={{
        width: W,
        height: H,
        display: "flex",
        flexDirection: "column",
        backgroundImage: gradient,
        fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        position: "relative",
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          padding: `${CONTENT_PAD_TOP}px ${CONTENT_PAD_X}px 0 ${CONTENT_PAD_X}px`,
          gap: 48,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          {wordmark}
        </div>
        {tickerBlock}
        {fvPriceRows}
        {verdictPill}
      </div>
      {/* Chart and narrative anchored above the SEBI banner so they're
          always above the disclaimer regardless of body height. */}
      <div
        style={{
          position: "absolute",
          left: CONTENT_PAD_X,
          right: CONTENT_PAD_X,
          bottom: SEBI_H + 80,
          display: "flex",
          flexDirection: "column",
          gap: 36,
          alignItems: "flex-start",
        }}
      >
        {chartBlock}
        {narrativeBlock}
        {cta}
      </div>
      {sebiBanner}
    </div>
  ) : (
    <div
      style={{
        width: W,
        height: H,
        display: "flex",
        flexDirection: "column",
        backgroundImage: gradient,
        fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        position: "relative",
      }}
    >
      {/* Header strip */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: `${CONTENT_PAD_TOP}px ${CONTENT_PAD_X}px 0 ${CONTENT_PAD_X}px`,
        }}
      >
        {tickerBlock}
        {wordmark}
      </div>
      {/* Main row: FV/price on the left, fan-out chart on the right.
          Anchored so the SEBI banner has a clear 192px reservation.
          `top: 170` clears the header strip without colliding with the
          ticker block; `bottom: SEBI_H + 24` keeps the CTA line out of
          the disclaimer banner border. */}
      <div
        style={{
          position: "absolute",
          left: CONTENT_PAD_X,
          right: CONTENT_PAD_X,
          top: 170,
          bottom: SEBI_H + 24,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 32,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 16, flex: 1 }}>
          {fvPriceRows}
          {verdictPill}
          {narrativeBlock}
          {cta}
        </div>
        {chartBlock}
      </div>
      {sebiBanner}
    </div>
  )

  return new ImageResponse(root, {
    width: W,
    height: H,
    headers: {
      // Match the analysis Share Report Card cache stance (1h edge,
      // 7d SWR). Keeps the share surface consistent across all three
      // OG routes and within the same revalidate window declared
      // above.
      "Cache-Control":
        "public, max-age=3600, s-maxage=3600, stale-while-revalidate=604800",
    },
  })
}
