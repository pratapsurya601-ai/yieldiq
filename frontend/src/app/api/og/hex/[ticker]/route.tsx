import { ImageResponse } from "next/og"
import type { NextRequest } from "next/server"

export const runtime = "edge"
export const revalidate = 3600

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.yieldiq.in"

interface HexAxisPayload {
  score?: number
  label?: string
  why?: string
  data_limited?: boolean
}

interface HexPayload {
  ticker?: string
  company_name?: string
  overall?: number
  axes?: Record<string, HexAxisPayload>
}

const AXIS_ORDER = ["value", "quality", "growth", "moat", "safety", "pulse"] as const
const AXIS_LABEL: Record<string, string> = {
  value: "Value",
  quality: "Quality",
  growth: "Growth",
  moat: "Moat",
  safety: "Safety",
  pulse: "Pulse",
}

function scoreColor(s: number): string {
  if (s >= 7) return "#10B981"
  if (s >= 4) return "#F59E0B"
  return "#EF4444"
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params
  const tickerUpper = (ticker || "").toUpperCase()
  const cleanTicker = tickerUpper.replace(/\.(NS|BO)$/i, "")

  let data: HexPayload = {}
  let fetchOk = false
  try {
    const full = tickerUpper.includes(".") ? tickerUpper : `${tickerUpper}.NS`
    const res = await fetch(
      `${API_BASE}/api/v1/hex/${encodeURIComponent(full)}`,
      { signal: AbortSignal.timeout(8000) }
    )
    if (res.ok) {
      data = (await res.json()) as HexPayload
      fetchOk = true
    }
  } catch {
    // fall through to fallback
  }

  const overall = Math.max(0, Math.min(10, Number(data.overall ?? 0)))
  const company = (data.company_name || cleanTicker).toString().slice(0, 60)

  // Hexagon geometry — 6 axes, 0..10 radial. SVG_TOP is the y-offset of
  // the SVG inside the root container — shared by the SVG itself and the
  // HTML overlays that replace <text> nodes (Satori in Next 16 rejects
  // <text> in SVG, so labels + numbers are positioned absolutely as
  // <div>s over the geometric shapes; see analysis/[ticker] for the
  // same pattern).
  const W = 1200
  const H = 1200
  const cx = 600
  const cy = 700
  const R = 340
  const SVG_TOP = 260

  const vertex = (i: number, valueOf10: number): [number, number] => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / 6
    const r = (Math.max(0, Math.min(10, valueOf10)) / 10) * R
    return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)]
  }

  const ringPolygon = (val: number) =>
    Array.from({ length: 6 }, (_, i) => vertex(i, val).join(",")).join(" ")

  const scores = AXIS_ORDER.map((k) => {
    const v = data.axes?.[k]?.score
    return typeof v === "number" ? Math.max(0, Math.min(10, v)) : 0
  })

  const dataPoly = scores.map((s, i) => vertex(i, s).join(",")).join(" ")

  // Label positions (outside)
  const labelPos = AXIS_ORDER.map((_, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / 6
    const rr = R + 60
    return [cx + rr * Math.cos(angle), cy + rr * Math.sin(angle)] as [number, number]
  })

  return new ImageResponse(
    (
      <div
        style={{
          width: W,
          height: H,
          display: "flex",
          flexDirection: "column",
          backgroundImage:
            "linear-gradient(135deg, #0f172a 0%, #1e40af 100%)",
          padding: "60px 70px",
          fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
          position: "relative",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <div
              style={{
                width: 56,
                height: 56,
                borderRadius: 14,
                background: "linear-gradient(135deg, #3B82F6, #06B6D4)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "white",
                fontSize: 32,
                fontWeight: 800,
              }}
            >
              Y
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <span
                style={{
                  color: "white",
                  fontSize: 40,
                  fontWeight: 900,
                  letterSpacing: -1,
                  display: "flex",
                  lineHeight: 1,
                }}
              >
                <span style={{ color: "#60A5FA" }}>Yield</span>
                <span>IQ</span>
              </span>
              <span
                style={{
                  color: "#94A3B8",
                  fontSize: 20,
                  fontWeight: 500,
                  marginTop: 4,
                  display: "flex",
                }}
              >
                The Hex
              </span>
            </div>
          </div>
          <div
            style={{
              background: "rgba(59,130,246,0.2)",
              border: "2px solid #3B82F6",
              color: "#BFDBFE",
              padding: "10px 24px",
              borderRadius: 999,
              fontSize: 22,
              fontWeight: 700,
              display: "flex",
            }}
          >
            6-Axis Profile
          </div>
        </div>

        {/* Ticker + company */}
        <div style={{ display: "flex", flexDirection: "column", marginTop: 30 }}>
          <span
            style={{
              color: "white",
              fontSize: 92,
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
              fontSize: 26,
              fontWeight: 500,
              marginTop: 10,
              display: "flex",
            }}
          >
            {company}
          </span>
        </div>

        {/* Hex — SVG holds ONLY geometric shapes; all typography is
            layered as absolutely-positioned HTML below. */}
        <svg
          width={W}
          height={780}
          style={{ position: "absolute", left: 0, top: SVG_TOP }}
        >
          {/* Grid rings */}
          {[2, 4, 6, 8, 10].map((v) => (
            <polygon
              key={v}
              points={ringPolygon(v)}
              fill="none"
              stroke="rgba(148,163,184,0.25)"
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
                stroke="rgba(148,163,184,0.25)"
                strokeWidth={1.5}
              />
            )
          })}
          {/* Data polygon */}
          {fetchOk && (
            <polygon
              points={dataPoly}
              fill="rgba(96,165,250,0.35)"
              stroke="#60A5FA"
              strokeWidth={4}
            />
          )}
          {/* Vertex circles only — numbers rendered as HTML overlays */}
          {fetchOk &&
            AXIS_ORDER.map((k, i) => {
              const [x, y] = vertex(i, scores[i])
              const color = scoreColor(scores[i])
              return <circle key={k} cx={x} cy={y} r={22} fill={color} />
            })}
          {/* Center composite disc — number overlaid as HTML */}
          <circle
            cx={cx}
            cy={cy}
            r={72}
            fill="rgba(15,23,42,0.85)"
            stroke="#60A5FA"
            strokeWidth={3}
          />
        </svg>

        {/* Axis labels — HTML overlays aligned to each hex vertex */}
        {AXIS_ORDER.map((k, i) => {
          const [x, y] = labelPos[i]
          return (
            <div
              key={`lbl-${k}`}
              style={{
                position: "absolute",
                left: x - 100,
                top: SVG_TOP + y - 16,
                width: 200,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#E2E8F0",
                fontSize: 26,
                fontWeight: 700,
                letterSpacing: 1,
              }}
            >
              {AXIS_LABEL[k].toUpperCase()}
            </div>
          )
        })}

        {/* Vertex score numbers */}
        {fetchOk &&
          AXIS_ORDER.map((k, i) => {
            const [x, y] = vertex(i, scores[i])
            return (
              <div
                key={`num-${k}`}
                style={{
                  position: "absolute",
                  left: x - 30,
                  top: SVG_TOP + y - 14,
                  width: 60,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#ffffff",
                  fontSize: 20,
                  fontWeight: 800,
                }}
              >
                {scores[i].toFixed(1)}
              </div>
            )
          })}

        {/* Center composite number + "/ 10" caption */}
        <div
          style={{
            position: "absolute",
            left: cx - 90,
            top: SVG_TOP + cy - 42,
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
              fontSize: 56,
              fontWeight: 900,
              lineHeight: 1,
              display: "flex",
            }}
          >
            {fetchOk ? overall.toFixed(1) : "\u2014"}
          </div>
          <div
            style={{
              color: "#94A3B8",
              fontSize: 18,
              fontWeight: 600,
              letterSpacing: 2,
              marginTop: 8,
              display: "flex",
            }}
          >
            / 10
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            position: "absolute",
            left: 70,
            right: 70,
            bottom: 50,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-end",
          }}
        >
          <span style={{ color: "#60A5FA", fontSize: 24, fontWeight: 700, display: "flex" }}>
            yieldiq.in/hex/{cleanTicker}
          </span>
          <span style={{ color: "#94A3B8", fontSize: 18, display: "flex" }}>
            {fetchOk ? "Model estimate. Not investment advice." : "Analysis unavailable \u2014 check back soon."}
          </span>
        </div>
      </div>
    ),
    {
      width: W,
      height: H,
      headers: {
        "Cache-Control": "public, max-age=3600, s-maxage=3600, stale-while-revalidate=86400",
      },
    }
  )
}
