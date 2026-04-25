import { ImageResponse } from "next/og"
import type { NextRequest } from "next/server"

// Edge runtime for fast OG image rendering (Satori + Resvg).
export const runtime = "edge"

// Cache at the CDN / Vercel edge for 30 minutes so repeat shares don't
// re-render the same card. OG scrapers (WhatsApp, Twitter, LinkedIn,
// Slack, Facebook) hit this URL once per link per day on average.
export const revalidate = 1800

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.yieldiq.in"

// Bumped when the SEBI vocabulary sweep renamed verdict labels
// ("Undervalued"/"Overvalued" → "Below Fair Value"/"Above Fair Value").
// CDN scrapers cache OG cards aggressively; the X-OG-Cache-Version header
// gives us a way to verify a refreshed card carries the new copy.
const OG_CACHE_VERSION = "v2-sebi-fv-labels"

interface OgData {
  ticker?: string
  fair_value?: number
  price?: number
  mos?: number
  score?: number
  verdict?: string
  moat?: string
  description?: string
}

// SEBI-safe verdict labels: descriptive, never imperative.
// `avoid` maps to "High Risk", `data_limited`/`unavailable` to "Under Review".
function verdictLabel(v?: string): string {
  switch (v) {
    case "undervalued": return "Below Fair Value"
    case "fairly_valued": return "Near Fair Value"
    case "overvalued": return "Above Fair Value"
    case "avoid": return "High Risk"
    case "data_limited":
    case "unavailable":
      return "Under Review"
    default: return "Under Review"
  }
}

function verdictBg(v?: string): string {
  switch (v) {
    case "undervalued": return "#10B981"
    case "fairly_valued": return "#3B82F6"
    case "overvalued": return "#F59E0B"
    case "avoid": return "#EF4444"
    default: return "#64748B"
  }
}

function scoreRingColor(s: number): string {
  if (s >= 60) return "#10B981" // green
  if (s >= 40) return "#F59E0B" // yellow
  return "#EF4444"              // red
}

function fmtPrice(n: number | undefined | null): string {
  if (n == null || isNaN(n) || n <= 0) return "\u2014"
  return `\u20B9${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
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
  const cleanTicker = tickerUpper.replace(".NS", "").replace(".BO", "")

  // Fetch from public og-data endpoint. If it fails for any reason we still
  // render a branded "Under Review" card instead of 500ing — OG scrapers
  // cache failures aggressively, so we must always return an image.
  let ogData: OgData = {}
  try {
    const fullTicker = tickerUpper.includes(".") ? tickerUpper : `${tickerUpper}.NS`
    const res = await fetch(
      `${API_BASE}/api/v1/analysis/${encodeURIComponent(fullTicker)}/og-data`,
      { signal: AbortSignal.timeout(8000) }
    )
    if (res.ok) ogData = (await res.json()) as OgData
  } catch {
    // fall through to safe defaults
  }

  const verdict = ogData.verdict || "data_limited"
  const fairValueNum = ogData.fair_value ?? 0
  const priceNum = ogData.price ?? 0
  const mos = ogData.mos ?? 0
  const score = Math.max(0, Math.min(100, Math.round(ogData.score ?? 0)))

  // data_limited / unavailable / FV<=0 => render "Under Review" with em dashes
  // for the valuation fields. Price can still show if we have one.
  const isUnderReview =
    verdict === "data_limited" ||
    verdict === "unavailable" ||
    !fairValueNum ||
    fairValueNum <= 0

  const verdictText = isUnderReview ? "Under Review" : verdictLabel(verdict)
  const verdictColor = isUnderReview ? "#64748B" : verdictBg(verdict)

  // Description field from the og-data endpoint is the company name / short
  // descriptor. Fall back to ticker if absent. Truncate aggressively so the
  // card never wraps awkwardly.
  const companyName = truncate((ogData.description || cleanTicker).toString(), 52)

  const fairValue = isUnderReview ? "\u2014" : fmtPrice(fairValueNum)
  const price = fmtPrice(priceNum)
  const mosText = isUnderReview
    ? "\u2014"
    : `${mos >= 0 ? "+" : ""}${mos.toFixed(1)}%`
  const mosColor = isUnderReview
    ? "#94A3B8"
    : mos >= 0
      ? "#10B981"
      : "#EF4444"

  const ringColor = scoreRingColor(score)

  // Score ring geometry — SVG arc showing `score`/100 as a coloured stroke
  // over a darker track. Satori supports SVG.
  const ringSize = 180
  const strokeWidth = 16
  const radius = (ringSize - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const dash = (score / 100) * circumference

  return new ImageResponse(
    (
      <div
        style={{
          width: 1200,
          height: 630,
          display: "flex",
          flexDirection: "column",
          backgroundImage:
            "linear-gradient(135deg, #0B1026 0%, #1E1B4B 45%, #020617 100%)",
          padding: "50px 60px",
          fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        }}
      >
        {/* Header: brand + verdict pill */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 12,
                background: "linear-gradient(135deg, #3B82F6, #06B6D4)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "white",
                fontSize: 24,
                fontWeight: 800,
              }}
            >
              Y
            </div>
            <span
              style={{
                color: "white",
                fontSize: 32,
                fontWeight: 800,
                letterSpacing: -0.5,
                display: "flex",
              }}
            >
              <span style={{ color: "#60A5FA" }}>Yield</span>
              <span>IQ</span>
            </span>
          </div>

          <div
            style={{
              background: `${verdictColor}22`,
              border: `2px solid ${verdictColor}`,
              color: verdictColor,
              padding: "10px 22px",
              borderRadius: 999,
              fontSize: 22,
              fontWeight: 700,
              display: "flex",
            }}
          >
            {verdictText}
          </div>
        </div>

        {/* Middle: ticker + company (left), score ring (right) */}
        <div
          style={{
            display: "flex",
            flex: 1,
            alignItems: "center",
            justifyContent: "space-between",
            gap: 40,
            marginTop: 10,
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", maxWidth: 760 }}>
            <span
              style={{
                color: "white",
                fontSize: 108,
                fontWeight: 900,
                lineHeight: 1,
                letterSpacing: -3,
                display: "flex",
              }}
            >
              {cleanTicker}
            </span>
            <span
              style={{
                color: "#CBD5E1",
                fontSize: 28,
                fontWeight: 500,
                lineHeight: 1.2,
                marginTop: 16,
                display: "flex",
              }}
            >
              {companyName}
            </span>
            {ogData.moat ? (
              <span
                style={{
                  color: "#94A3B8",
                  fontSize: 20,
                  marginTop: 12,
                  display: "flex",
                }}
              >
                {ogData.moat} Moat
              </span>
            ) : null}
          </div>

          {/* Score ring (SVG) */}
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
                r={radius}
                stroke="#1E293B"
                strokeWidth={strokeWidth}
                fill="none"
              />
              <circle
                cx={ringSize / 2}
                cy={ringSize / 2}
                r={radius}
                stroke={ringColor}
                strokeWidth={strokeWidth}
                fill="none"
                strokeDasharray={`${dash} ${circumference}`}
                strokeLinecap="round"
                transform={`rotate(-90 ${ringSize / 2} ${ringSize / 2})`}
              />
            </svg>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                zIndex: 1,
              }}
            >
              <span
                style={{
                  color: "white",
                  fontSize: 56,
                  fontWeight: 900,
                  lineHeight: 1,
                  display: "flex",
                }}
              >
                {score}
              </span>
              <span
                style={{
                  color: "#94A3B8",
                  fontSize: 14,
                  marginTop: 4,
                  letterSpacing: 2,
                  display: "flex",
                }}
              >
                / 100 SCORE
              </span>
            </div>
          </div>
        </div>

        {/* Bottom: three metrics + share URL */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-end",
            marginTop: 20,
          }}
        >
          <div style={{ display: "flex", gap: 50 }}>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <span
                style={{
                  color: "#94A3B8",
                  fontSize: 14,
                  textTransform: "uppercase",
                  letterSpacing: 2,
                  display: "flex",
                }}
              >
                Fair Value
              </span>
              <span
                style={{
                  color: "white",
                  fontSize: 38,
                  fontWeight: 800,
                  marginTop: 6,
                  display: "flex",
                }}
              >
                {fairValue}
              </span>
            </div>

            <div style={{ display: "flex", flexDirection: "column" }}>
              <span
                style={{
                  color: "#94A3B8",
                  fontSize: 14,
                  textTransform: "uppercase",
                  letterSpacing: 2,
                  display: "flex",
                }}
              >
                Price
              </span>
              <span
                style={{
                  color: "#CBD5E1",
                  fontSize: 30,
                  fontWeight: 600,
                  marginTop: 6,
                  display: "flex",
                }}
              >
                {price}
              </span>
            </div>

            <div style={{ display: "flex", flexDirection: "column" }}>
              <span
                style={{
                  color: "#94A3B8",
                  fontSize: 14,
                  textTransform: "uppercase",
                  letterSpacing: 2,
                  display: "flex",
                }}
              >
                Margin of Safety
              </span>
              <span
                style={{
                  color: mosColor,
                  fontSize: 38,
                  fontWeight: 800,
                  marginTop: 6,
                  display: "flex",
                }}
              >
                {mosText}
              </span>
            </div>
          </div>

          <span
            style={{
              color: "#64748B",
              fontSize: 16,
              display: "flex",
            }}
          >
            yieldiq.in/stocks/{cleanTicker}/fair-value
          </span>
        </div>
      </div>
    ),
    {
      width: 1200,
      height: 630,
      headers: {
        "Cache-Control":
          "public, max-age=0, s-maxage=1800, stale-while-revalidate=86400",
        "X-OG-Cache-Version": OG_CACHE_VERSION,
      },
    }
  )
}
