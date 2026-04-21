import { ImageResponse } from "next/og"
import type { NextRequest } from "next/server"

/**
 * 1080 x 1920 "Share Report Card" — the portrait, Instagram-Story /
 * Twitter-vertical optimised share surface for any ticker. Public,
 * unauthenticated, edge-rendered.
 *
 * Unlike /api/og/[ticker] (1200x630, Open-Graph link preview) and
 * /api/og/prism/[ticker] (1200x1200 branded Prism), this endpoint
 * returns a tall vertical image designed to be saved directly and
 * posted to IG Story, WhatsApp Status or a Twitter vertical. It is
 * the hero artefact of the "Share Report Card" button on the
 * analysis page.
 *
 * Data sources (both unauthed, both edge-safe):
 *   - /api/v1/public/stock-summary/{ticker}  — FV / price / verdict
 *   - /api/v1/hex/{ticker}                    — 6-axis Prism scores
 *
 * The hex is drawn as SVG polygons/circles (Satori supports those)
 * with text rendered as absolutely-positioned <div> overlays — the
 * Satori version Next 16 ships with rejects <text> SVG nodes (see
 * "text nodes are not currently supported" error), so we keep the
 * SVG strictly geometric and layer the typography in flexbox.
 */

export const runtime = "edge"
// Edge revalidate is just a hint — the real cache headers below drive
// Vercel's edge cache. Matched to the other OG routes in this tree.
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
  verdict?: string
  score?: number
  grade?: string
  moat?: string
}

interface HexAxisPayload {
  score?: number | null
  data_limited?: boolean
}

interface HexPayload {
  overall?: number
  axes?: Record<string, HexAxisPayload>
}

// Axis order starts at 12 o'clock and rotates clockwise. Keeping
// pulse at the top mirrors the editorial Prism hex in the app — the
// "signature" pillar is visually anchored at the crown of the card.
const AXIS_ORDER = ["pulse", "quality", "moat", "safety", "growth", "value"] as const
const AXIS_LABEL: Record<string, string> = {
  pulse: "PULSE",
  quality: "QUALITY",
  moat: "MOAT",
  safety: "SAFETY",
  growth: "GROWTH",
  value: "VALUE",
}

function verdictText(v: string | undefined, mos: number): string {
  // The card shows "UNDERVALUED by 32.7%" etc. — much more striking
  // than a bare "Undervalued". We lean into the MoS magnitude because
  // that's the number readers remember.
  const absMos = Math.abs(mos)
  switch (v) {
    case "undervalued":
      return `UNDERVALUED by ${absMos.toFixed(1)}%`
    case "fairly_valued":
      return "FAIRLY VALUED"
    case "overvalued":
      return `OVERVALUED by ${absMos.toFixed(1)}%`
    case "avoid":
      return "HIGH RISK"
    case "data_limited":
    case "unavailable":
      return "UNDER REVIEW"
    default:
      return "UNDER REVIEW"
  }
}

function verdictColor(v: string | undefined): string {
  switch (v) {
    case "undervalued":
      return "#10B981"
    case "fairly_valued":
      return "#F59E0B"
    case "overvalued":
      return "#EF4444"
    case "avoid":
      return "#EF4444"
    default:
      return "#64748B"
  }
}

function fmtINR(n: number | undefined | null): string {
  if (n == null || !Number.isFinite(n) || n <= 0) return "\u2014"
  return `\u20B9${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
}

function truncate(s: string, n: number): string {
  if (!s) return ""
  return s.length > n ? s.slice(0, n - 1).trimEnd() + "\u2026" : s
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params
  const tickerUpper = (ticker || "").toUpperCase()
  const cleanTicker = tickerUpper.replace(/\.(NS|BO)$/i, "")
  const fullTicker = tickerUpper.includes(".") ? tickerUpper : `${tickerUpper}.NS`

  // Fire both requests in parallel — they're independent. Timeout each
  // at 8s so a slow upstream doesn't 504 the image entirely; we fall
  // back to an "Under Review" layout rather than surfacing the error,
  // because OG scrapers cache failures aggressively.
  const [summaryRes, hexRes] = await Promise.allSettled([
    fetch(
      `${API_BASE}/api/v1/public/stock-summary/${encodeURIComponent(fullTicker)}`,
      { signal: AbortSignal.timeout(8000) }
    ).then((r) => (r.ok ? (r.json() as Promise<StockSummary>) : null)),
    fetch(
      `${API_BASE}/api/v1/hex/${encodeURIComponent(fullTicker)}`,
      { signal: AbortSignal.timeout(8000) }
    ).then((r) => (r.ok ? (r.json() as Promise<HexPayload>) : null)),
  ])

  const summary: StockSummary =
    summaryRes.status === "fulfilled" && summaryRes.value ? summaryRes.value : {}
  const hex: HexPayload =
    hexRes.status === "fulfilled" && hexRes.value ? hexRes.value : {}

  const fairValue = Number(summary.fair_value ?? 0)
  const price = Number(summary.current_price ?? 0)
  const mos = Number(summary.mos ?? 0)
  const verdict = summary.verdict || "data_limited"
  const score100 = Math.max(0, Math.min(100, Math.round(Number(summary.score ?? 0))))
  const grade = (summary.grade || "").toString().slice(0, 2) || "\u2014"
  const moat = (summary.moat || "").toString()
  const sector = (summary.sector || "").toString()
  const companyName = truncate(summary.company_name || cleanTicker, 38)

  const isUnderReview =
    verdict === "data_limited" ||
    verdict === "unavailable" ||
    !fairValue ||
    fairValue <= 0

  // ─── Hex geometry ─────────────────────────────────────────────────
  // 1080x1920 portrait. The SVG canvas for the hex is a 900x820 box
  // pinned with absolute positioning so ticker block can sit above
  // and FV / CTA can sit below without flex measuring the hex.
  const SVG_W = 900
  const SVG_H = 820
  const SVG_LEFT = (1080 - SVG_W) / 2
  // Pushed down so the PULSE label at 12 o'clock clears the verdict
  // banner. The hex uses an inner radius so there's breathing room
  // between the top-vertex label and the banner.
  const SVG_TOP = 540
  const cx = SVG_W / 2
  const cy = SVG_H / 2 - 30
  const R = 270

  const vertex = (i: number, valueOf10: number): [number, number] => {
    // -PI/2 puts the first axis at 12 o'clock; clockwise from there.
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / 6
    const r = (Math.max(0, Math.min(10, valueOf10)) / 10) * R
    return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)]
  }

  const ringPolygon = (val: number) =>
    Array.from({ length: 6 }, (_, i) => vertex(i, val).join(",")).join(" ")

  const scores = AXIS_ORDER.map((k) => {
    const v = hex.axes?.[k]?.score
    return typeof v === "number" && Number.isFinite(v)
      ? Math.max(0, Math.min(10, v))
      : 0
  })
  const hasHex = AXIS_ORDER.some(
    (k) => typeof hex.axes?.[k]?.score === "number"
  )

  const dataPoly = scores.map((s, i) => vertex(i, s).join(",")).join(" ")

  // Absolute-pixel positions (relative to the full 1080x1920 card)
  // for axis labels and per-vertex score pills. Offsetting by
  // SVG_LEFT / SVG_TOP lets the overlay divs align pixel-perfect
  // over the SVG even though they live outside the <svg> element.
  const labelDivs = AXIS_ORDER.map((k, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / 6
    // Top (pulse) vertex gets extra clearance so PULSE never crowds
    // the verdict banner; other vertices use the standard offset.
    const isTop = i === 0
    const rr = isTop ? R + 40 : R + 64
    const x = cx + rr * Math.cos(angle)
    const y = cy + rr * Math.sin(angle)
    return { k, label: AXIS_LABEL[k], x: x + SVG_LEFT, y: y + SVG_TOP }
  })

  const pillDivs = AXIS_ORDER.map((_, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / 6
    const rr = R - 22
    const x = cx + rr * Math.cos(angle)
    const y = cy + rr * Math.sin(angle)
    const s = scores[i]
    const c = s >= 7 ? "#10B981" : s >= 4 ? "#F59E0B" : "#EF4444"
    return { s, c, x: x + SVG_LEFT, y: y + SVG_TOP }
  })

  const centerOverall =
    typeof hex.overall === "number"
      ? Math.max(0, Math.min(10, hex.overall))
      : score100 / 10

  const vColor = verdictColor(isUnderReview ? "data_limited" : verdict)
  const vText = verdictText(verdict, mos)

  // Score ring geometry (the small badge top-right).
  const ringSize = 150
  const ringStroke = 12
  const ringR = (ringSize - ringStroke) / 2
  const ringCirc = 2 * Math.PI * ringR
  const ringDash = (score100 / 100) * ringCirc
  const ringColor =
    score100 >= 75 ? "#10B981" :
    score100 >= 55 ? "#3B82F6" :
    score100 >= 35 ? "#F59E0B" : "#EF4444"

  // Pill label helper — Satori needs each block to be a self-contained
  // flex item; extracting the score-pill JSX keeps the map readable.
  return new ImageResponse(
    (
      <div
        style={{
          width: 1080,
          height: 1920,
          display: "flex",
          flexDirection: "column",
          backgroundImage:
            "linear-gradient(180deg, #0A0F1F 0%, #131B3A 40%, #1A1F3A 100%)",
          fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
          position: "relative",
        }}
      >
        {/* ─── Header strip: wordmark + score ring ───────────────── */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "64px 64px 0 64px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
            <div
              style={{
                width: 64,
                height: 64,
                borderRadius: 16,
                background: "linear-gradient(135deg, #3B82F6, #06B6D4)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "white",
                fontSize: 38,
                fontWeight: 900,
              }}
            >
              Y
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <div
                style={{
                  fontSize: 46,
                  fontWeight: 900,
                  letterSpacing: -1.5,
                  display: "flex",
                  lineHeight: 1,
                }}
              >
                <span style={{ color: "#60A5FA" }}>Yield</span>
                <span style={{ color: "#ffffff" }}>IQ</span>
              </div>
              <div
                style={{
                  color: "#94A3B8",
                  fontSize: 20,
                  fontWeight: 500,
                  marginTop: 6,
                  letterSpacing: 2,
                  display: "flex",
                  textTransform: "uppercase",
                }}
              >
                The Prism
              </div>
            </div>
          </div>

          {/* Score ring (top right) — geometry in SVG, digits in a
              flex-centered absolute div on top. */}
          <div
            style={{
              width: ringSize,
              height: ringSize,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              position: "relative",
              flexShrink: 0,
            }}
          >
            <svg
              width={ringSize}
              height={ringSize}
              style={{ position: "absolute", top: 0, left: 0 }}
            >
              <circle
                cx={ringSize / 2}
                cy={ringSize / 2}
                r={ringR}
                stroke="#1E293B"
                strokeWidth={ringStroke}
                fill="none"
              />
              {!isUnderReview && (
                <circle
                  cx={ringSize / 2}
                  cy={ringSize / 2}
                  r={ringR}
                  stroke={ringColor}
                  strokeWidth={ringStroke}
                  fill="none"
                  strokeDasharray={`${ringDash} ${ringCirc}`}
                  strokeLinecap="round"
                  transform={`rotate(-90 ${ringSize / 2} ${ringSize / 2})`}
                />
              )}
            </svg>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
              }}
            >
              <div
                style={{
                  color: "#ffffff",
                  fontSize: 44,
                  fontWeight: 900,
                  lineHeight: 1,
                  display: "flex",
                }}
              >
                {isUnderReview ? "\u2014" : grade}
              </div>
              <div
                style={{
                  color: "#94A3B8",
                  fontSize: 14,
                  marginTop: 4,
                  letterSpacing: 2,
                  display: "flex",
                }}
              >
                {isUnderReview ? "GRADE" : `${score100} / 100`}
              </div>
            </div>
          </div>
        </div>

        {/* ─── Ticker block ───────────────────────────────────────── */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            padding: "42px 64px 0 64px",
          }}
        >
          <div
            style={{
              color: "#ffffff",
              fontSize: 128,
              fontWeight: 900,
              lineHeight: 1,
              letterSpacing: -4,
              display: "flex",
            }}
          >
            {cleanTicker}
          </div>
          <div
            style={{
              color: "#CBD5E1",
              fontSize: 34,
              fontWeight: 500,
              lineHeight: 1.2,
              marginTop: 14,
              display: "flex",
            }}
          >
            {companyName}
          </div>
          {sector ? (
            <div style={{ display: "flex", marginTop: 16 }}>
              <div
                style={{
                  color: "#60A5FA",
                  fontSize: 20,
                  fontWeight: 700,
                  letterSpacing: 1.5,
                  padding: "8px 18px",
                  background: "rgba(59,130,246,0.12)",
                  border: "1px solid rgba(59,130,246,0.35)",
                  borderRadius: 999,
                  display: "flex",
                  textTransform: "uppercase",
                }}
              >
                {truncate(sector, 28)}
              </div>
            </div>
          ) : null}
        </div>

        {/* ─── Verdict banner ─────────────────────────────────────── */}
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            marginTop: 28,
            padding: "0 64px",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "18px 36px",
              background: `${vColor}22`,
              border: `2px solid ${vColor}`,
              borderRadius: 20,
              color: vColor,
              fontSize: 32,
              fontWeight: 800,
              letterSpacing: 1,
              textTransform: "uppercase",
            }}
          >
            {vText}
          </div>
        </div>

        {/* ─── Prism Hex — shapes as SVG, labels as HTML ────────── */}
        <svg
          width={SVG_W}
          height={SVG_H}
          style={{ position: "absolute", left: SVG_LEFT, top: SVG_TOP }}
        >
          <defs>
            <linearGradient id="hex-fill" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="rgba(56,189,248,0.45)" />
              <stop offset="100%" stopColor="rgba(59,130,246,0.25)" />
            </linearGradient>
          </defs>

          {/* Grid rings */}
          {[2, 4, 6, 8, 10].map((v) => (
            <polygon
              key={v}
              points={ringPolygon(v)}
              fill="none"
              stroke="rgba(148,163,184,0.20)"
              strokeWidth={1.5}
            />
          ))}

          {/* Spokes */}
          {AXIS_ORDER.map((_, i) => {
            const [x, y] = vertex(i, 10)
            return (
              <line
                key={i}
                x1={cx}
                y1={cy}
                x2={x}
                y2={y}
                stroke="rgba(148,163,184,0.20)"
                strokeWidth={1.5}
              />
            )
          })}

          {/* Data polygon — the hero shape */}
          {hasHex && !isUnderReview && (
            <polygon
              points={dataPoly}
              fill="url(#hex-fill)"
              stroke="#38BDF8"
              strokeWidth={5}
              strokeLinejoin="round"
            />
          )}

          {/* Per-vertex score pills — just the circles; the number
              goes in an HTML overlay so we don't need <text>. */}
          {hasHex && !isUnderReview &&
            AXIS_ORDER.map((_, i) => {
              const [x, y] = vertex(i, scores[i])
              const s = scores[i]
              const c = s >= 7 ? "#10B981" : s >= 4 ? "#F59E0B" : "#EF4444"
              return (
                <circle
                  key={i}
                  cx={x}
                  cy={y}
                  r={24}
                  fill={c}
                  opacity={0.95}
                />
              )
            })}

          {/* Center composite disc — number overlaid as HTML below. */}
          <circle
            cx={cx}
            cy={cy}
            r={84}
            fill="rgba(10,15,31,0.92)"
            stroke="#38BDF8"
            strokeWidth={3}
          />
        </svg>

        {/* Axis labels (HTML overlay, aligned to the SVG frame) */}
        {labelDivs.map(({ k, label, x, y }) => (
          <div
            key={k}
            style={{
              position: "absolute",
              left: x - 100,
              top: y - 18,
              width: 200,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#E2E8F0",
              fontSize: 26,
              fontWeight: 800,
              letterSpacing: 2,
            }}
          >
            {label}
          </div>
        ))}

        {/* Vertex score-pill numbers */}
        {hasHex && !isUnderReview &&
          pillDivs.map((p, i) => {
            // Only draw the number when the vertex was actually drawn
            // as a filled pill — skip zeros so we don't stamp "0.0" on
            // the grid origin for missing axes.
            const drawn = scores[i] > 0
            if (!drawn) return null
            const [vx, vy] = vertex(i, scores[i])
            return (
              <div
                key={i}
                style={{
                  position: "absolute",
                  left: vx + SVG_LEFT - 30,
                  top: vy + SVG_TOP - 16,
                  width: 60,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#ffffff",
                  fontSize: 22,
                  fontWeight: 900,
                }}
              >
                {p.s.toFixed(1)}
              </div>
            )
          })}

        {/* Center composite number + "/ 10" caption */}
        <div
          style={{
            position: "absolute",
            left: SVG_LEFT + cx - 90,
            top: SVG_TOP + cy - 44,
            width: 180,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <div
            style={{
              color: "#ffffff",
              fontSize: 64,
              fontWeight: 900,
              lineHeight: 1,
              display: "flex",
            }}
          >
            {isUnderReview ? "\u2014" : centerOverall.toFixed(1)}
          </div>
          <div
            style={{
              color: "#94A3B8",
              fontSize: 18,
              fontWeight: 700,
              letterSpacing: 3,
              marginTop: 10,
              display: "flex",
            }}
          >
            / 10
          </div>
        </div>

        {/* ─── Fair Value vs Price strip ──────────────────────────── */}
        <div
          style={{
            position: "absolute",
            left: 64,
            right: 64,
            bottom: 360,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 24,
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
            <div
              style={{
                color: "#64748B",
                fontSize: 18,
                fontWeight: 700,
                letterSpacing: 2,
                textTransform: "uppercase",
                display: "flex",
              }}
            >
              Fair Value
            </div>
            <div
              style={{
                color: "#ffffff",
                fontSize: 54,
                fontWeight: 900,
                marginTop: 6,
                display: "flex",
                lineHeight: 1,
              }}
            >
              {isUnderReview ? "\u2014" : fmtINR(fairValue)}
            </div>
          </div>
          <div
            style={{
              width: 2,
              height: 72,
              background: "rgba(148,163,184,0.25)",
              display: "flex",
            }}
          />
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              flex: 1,
              alignItems: "flex-end",
            }}
          >
            <div
              style={{
                color: "#64748B",
                fontSize: 18,
                fontWeight: 700,
                letterSpacing: 2,
                textTransform: "uppercase",
                display: "flex",
              }}
            >
              Price
            </div>
            <div
              style={{
                color: "#CBD5E1",
                fontSize: 54,
                fontWeight: 900,
                marginTop: 6,
                display: "flex",
                lineHeight: 1,
              }}
            >
              {fmtINR(price)}
            </div>
          </div>
        </div>

        {/* ─── Moat chip ─────────────────────────────────────────── */}
        {moat && !isUnderReview ? (
          <div
            style={{
              position: "absolute",
              left: 64,
              right: 64,
              bottom: 280,
              display: "flex",
              justifyContent: "center",
            }}
          >
            <div
              style={{
                color: "#E2E8F0",
                fontSize: 22,
                fontWeight: 700,
                padding: "10px 22px",
                background: "rgba(30,41,59,0.65)",
                border: "1px solid rgba(148,163,184,0.25)",
                borderRadius: 999,
                letterSpacing: 1,
                display: "flex",
              }}
            >
              {moat} MOAT
            </div>
          </div>
        ) : null}

        {/* ─── CTA + watermark ───────────────────────────────────── */}
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: 64,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
          }}
        >
          <div
            style={{
              color: "#94A3B8",
              fontSize: 24,
              fontWeight: 500,
              display: "flex",
              letterSpacing: 0.5,
            }}
          >
            Analyze any stock at
          </div>
          <div
            style={{
              color: "#60A5FA",
              fontSize: 44,
              fontWeight: 900,
              letterSpacing: -0.5,
              marginTop: 12,
              display: "flex",
            }}
          >
            yieldiq.in
          </div>
          <div
            style={{
              color: "#475569",
              fontSize: 16,
              fontWeight: 500,
              marginTop: 18,
              display: "flex",
            }}
          >
            Model estimate. Not investment advice.
          </div>
        </div>
      </div>
    ),
    {
      width: 1080,
      height: 1920,
      headers: {
        // FIX-OG-CACHE-SYNC (2026-04-22): previous value was
        //   max-age=3600, s-maxage=86400 (1d edge), SWR=604800 (7d)
        // — mismatched with `revalidate = 3600` above. Meant a user
        // who shared a card then updated their thesis could have the
        // stale image served for up to 23h. Now all three match the
        // 1-hour revalidate window; SWR=7d stays as a graceful
        // degradation layer (edge can serve stale while refreshing
        // in the background).
        "Cache-Control":
          "public, max-age=3600, s-maxage=3600, stale-while-revalidate=604800",
      },
    }
  )
}
