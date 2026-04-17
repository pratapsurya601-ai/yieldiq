import { ImageResponse } from "next/og"
import type { NextRequest } from "next/server"

export const runtime = "edge"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

function verdictBg(v?: string): string {
  switch (v) {
    case "undervalued": return "#10B981"
    case "fairly_valued": return "#3B82F6"
    case "overvalued": return "#F59E0B"
    case "avoid": return "#EF4444"
    default: return "#6B7280"
  }
}

function scoreRingColor(s: number): string {
  if (s >= 75) return "#10B981"
  if (s >= 55) return "#3B82F6"
  if (s >= 35) return "#F59E0B"
  return "#EF4444"
}

function fmtPrice(n: number): string {
  if (!n || isNaN(n)) return "\u2014"
  return `\u20B9${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params
  const cleanTicker = ticker.toUpperCase().replace(".NS", "").replace(".BO", "")

  // Fetch OG data from existing no-auth endpoint
  let ogData: Record<string, unknown> = {}
  try {
    const fullTicker = ticker.toUpperCase().includes(".") ? ticker.toUpperCase() : `${ticker.toUpperCase()}.NS`
    const res = await fetch(`${API_BASE}/api/v1/analysis/${fullTicker}/og-data`, {
      signal: AbortSignal.timeout(8000),
    })
    if (res.ok) ogData = await res.json()
  } catch {
    // Fall through to defaults
  }

  const score = (ogData.score as number) || 0
  const verdict = (ogData.verdict as string) || ""
  // SEBI-safe: map 'avoid' to 'HIGH RISK' (descriptive, not advice)
  const verdictMap: Record<string, string> = {
    undervalued: "UNDERVALUED",
    fairly_valued: "FAIRLY VALUED",
    overvalued: "OVERVALUED",
    avoid: "HIGH RISK",
    data_limited: "DATA LIMITED",
    unavailable: "UNAVAILABLE",
  }
  const verdictText = verdictMap[verdict] || verdict.replace(/_/g, " ").toUpperCase() || "ANALYSIS"
  const fairValue = fmtPrice(ogData.fair_value as number)
  const price = fmtPrice(ogData.price as number)
  const mos = (ogData.mos as number) || 0
  const mosSign = mos >= 0 ? "+" : ""
  const ringColor = scoreRingColor(score)

  return new ImageResponse(
    (
      <div
        style={{
          width: 1200,
          height: 630,
          display: "flex",
          flexDirection: "column",
          background: "linear-gradient(135deg, #0F172A 0%, #1E293B 50%, #0F172A 100%)",
          padding: "50px 60px",
          fontFamily: "system-ui, -apple-system, sans-serif",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <div
              style={{
                width: 40, height: 40, borderRadius: 10,
                background: "linear-gradient(135deg, #3B82F6, #06B6D4)",
                display: "flex", alignItems: "center", justifyContent: "center",
                color: "white", fontSize: 20, fontWeight: 800,
              }}
            >
              Y
            </div>
            <span style={{ color: "#3B82F6", fontSize: 24, fontWeight: 800, letterSpacing: 4 }}>
              YIELDIQ
            </span>
          </div>
          <span style={{ color: "#64748B", fontSize: 18 }}>yieldiq.in</span>
        </div>

        {/* Main content */}
        <div style={{ display: "flex", flex: 1, alignItems: "center", gap: "60px", marginTop: 20 }}>
          {/* Left side — ticker info */}
          <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
            <span style={{ color: "white", fontSize: 56, fontWeight: 800, lineHeight: 1.1 }}>
              {cleanTicker}
            </span>

            {/* Verdict badge */}
            <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 20 }}>
              <div
                style={{
                  background: verdictBg(verdict),
                  color: "white",
                  padding: "8px 20px",
                  borderRadius: 8,
                  fontSize: 18,
                  fontWeight: 700,
                }}
              >
                {verdictText}
              </div>
              <span
                style={{
                  color: mos >= 0 ? "#10B981" : "#EF4444",
                  fontSize: 28,
                  fontWeight: 700,
                }}
              >
                {mosSign}{mos.toFixed(1)}% MoS
              </span>
            </div>

            {/* Price vs Fair Value */}
            <div style={{ display: "flex", gap: 40, marginTop: 30 }}>
              <div style={{ display: "flex", flexDirection: "column" }}>
                <span style={{ color: "#94A3B8", fontSize: 14, textTransform: "uppercase", letterSpacing: 2 }}>
                  Price
                </span>
                <span style={{ color: "white", fontSize: 32, fontWeight: 700, fontFamily: "monospace" }}>
                  {price}
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column" }}>
                <span style={{ color: "#94A3B8", fontSize: 14, textTransform: "uppercase", letterSpacing: 2 }}>
                  Fair Value
                </span>
                <span style={{ color: "white", fontSize: 32, fontWeight: 700, fontFamily: "monospace" }}>
                  {fairValue}
                </span>
              </div>
            </div>
          </div>

          {/* Right side — score circle */}
          <div
            style={{
              width: 160, height: 160, borderRadius: "50%",
              border: `8px solid ${ringColor}`,
              display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <span style={{ color: "white", fontSize: 56, fontWeight: 800, lineHeight: 1 }}>
              {score}
            </span>
            <span style={{ color: "#94A3B8", fontSize: 12, textTransform: "uppercase", letterSpacing: 2, marginTop: 4 }}>
              Score
            </span>
          </div>
        </div>

        {/* Footer */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10 }}>
          <span style={{ color: "#475569", fontSize: 14 }}>
            Free DCF valuation for Indian stocks
          </span>
          <span style={{ color: "#475569", fontSize: 12 }}>
            Model estimates only &mdash; not investment advice
          </span>
        </div>
      </div>
    ),
    {
      width: 1200,
      height: 630,
    }
  )
}
