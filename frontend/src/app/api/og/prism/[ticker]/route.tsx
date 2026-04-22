import { ImageResponse } from "next/og"
import type { NextRequest } from "next/server"

export const runtime = "edge"
export const revalidate = 3600

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.yieldiq.in"

// Minimal subset of the Prism payload the OG image needs. We don't import
// from @/components/prism/types because edge-runtime compilation of shared
// type files has been flaky — inlining keeps this route self-contained.
interface PillarPayload {
  key?: string
  score?: number | null
  label?: string
  why?: string
  data_limited?: boolean
}

interface PrismPayload {
  ticker?: string
  company_name?: string
  verdict_label?: string
  verdict_band?: string
  overall?: number
  pillars?: PillarPayload[]
}

// Canonical order — matches `PRISM_PILLAR_ORDER` in @/lib/prism.
// Duplicated inline because Satori edge runtime can't import runtime modules.
const PILLAR_ORDER = ["pulse", "quality", "moat", "safety", "growth", "value"] as const
const PILLAR_LABEL: Record<string, string> = {
  pulse: "Pulse",
  quality: "Quality",
  moat: "Moat",
  safety: "Safety",
  growth: "Growth",
  value: "Value",
}
const PILLAR_COLOR: Record<string, string> = {
  pulse: "#3B82F6",
  quality: "#10B981",
  moat: "#0D9488",
  safety: "#3B82F6",
  growth: "#EAB308",
  value: "#F97316",
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

  let data: PrismPayload = {}
  let fetchOk = false
  try {
    const full = tickerUpper.includes(".") ? tickerUpper : `${tickerUpper}.NS`
    const res = await fetch(
      `${API_BASE}/api/v1/prism/${encodeURIComponent(full)}`,
      { signal: AbortSignal.timeout(8000) }
    )
    if (res.ok) {
      data = (await res.json()) as PrismPayload
      fetchOk = true
    }
  } catch {
    // fall through to fallback layout
  }

  const overall = Math.max(0, Math.min(10, Number(data.overall ?? 0)))
  const company = (data.company_name || cleanTicker).toString().slice(0, 60)
  const verdictLabel = (data.verdict_label || "Analysis unavailable").slice(0, 40)

  // Build score map keyed by pillar key.
  const scoreByKey: Record<string, number | null> = {}
  for (const p of data.pillars || []) {
    if (!p.key) continue
    scoreByKey[p.key] =
      typeof p.score === "number" ? Math.max(0, Math.min(10, p.score)) : null
  }
  const scores = PILLAR_ORDER.map((k) => {
    const v = scoreByKey[k]
    return typeof v === "number" ? v : 0
  })

  // Hexagon geometry for the Signature.
  const W = 1200
  const H = 1200
  const cx = 600
  const cy = 640
  const R = 300

  const vertex = (i: number, valueOf10: number): [number, number] => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / 6
    const r = (Math.max(0, Math.min(10, valueOf10)) / 10) * R
    return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)]
  }

  const ringPolygon = (val: number) =>
    Array.from({ length: 6 }, (_, i) => vertex(i, val).join(",")).join(" ")

  const dataPoly = scores.map((s, i) => vertex(i, s).join(",")).join(" ")

  const labelPos = PILLAR_ORDER.map((_, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / 6
    const rr = R + 56
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
          backgroundImage: "linear-gradient(135deg, #0f172a 0%, #1e40af 100%)",
          fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
          position: "relative",
        }}
      >
        {/* Header (80px tall) */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "30px 70px 0 70px",
            height: 80,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: 12,
                background: "linear-gradient(135deg, #3B82F6, #06B6D4)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "white",
                fontSize: 28,
                fontWeight: 800,
              }}
            >
              Y
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <span
                style={{
                  color: "white",
                  fontSize: 34,
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
                  fontSize: 16,
                  fontWeight: 500,
                  marginTop: 2,
                  display: "flex",
                }}
              >
                The Prism
              </span>
            </div>
          </div>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-end",
            }}
          >
            <span
              style={{
                color: "white",
                fontSize: 52,
                fontWeight: 900,
                lineHeight: 1,
                letterSpacing: -2,
                display: "flex",
              }}
            >
              {cleanTicker}
            </span>
            <span
              style={{
                color: "#CBD5E1",
                fontSize: 18,
                fontWeight: 500,
                marginTop: 6,
                display: "flex",
                maxWidth: 520,
              }}
            >
              {company}
            </span>
          </div>
        </div>

        {/* Signature (center 700×700, approximately) */}
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            marginTop: 20,
          }}
        >
          <svg width={W} height={720} style={{ position: "absolute", left: 0, top: 110 }}>
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
            {PILLAR_ORDER.map((_, i) => {
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
            {fetchOk && (
              <polygon
                points={dataPoly}
                fill="rgba(96,165,250,0.35)"
                stroke="#60A5FA"
                strokeWidth={4}
              />
            )}
            {fetchOk &&
              PILLAR_ORDER.map((k, i) => {
                const [x, y] = vertex(i, scores[i])
                const color = PILLAR_COLOR[k] || scoreColor(scores[i])
                return (
                  <g key={k}>
                    <circle cx={x} cy={y} r={20} fill={color} />
                    <text
                      x={x}
                      y={y + 1}
                      textAnchor="middle"
                      dominantBaseline="central"
                      fontSize={18}
                      fontWeight={800}
                      fill="#ffffff"
                    >
                      {scores[i].toFixed(1)}
                    </text>
                  </g>
                )
              })}
            {PILLAR_ORDER.map((k, i) => {
              const [x, y] = labelPos[i]
              return (
                <text
                  key={k}
                  x={x}
                  y={y}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fontSize={24}
                  fontWeight={700}
                  fill="#E2E8F0"
                >
                  {PILLAR_LABEL[k].toUpperCase()}
                </text>
              )
            })}
            {/* Center composite score — huge */}
            <circle cx={cx} cy={cy} r={82} fill="rgba(15,23,42,0.9)" stroke="#60A5FA" strokeWidth={3} />
            <text
              x={cx}
              y={cy - 8}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={68}
              fontWeight={900}
              fill="#ffffff"
            >
              {fetchOk ? overall.toFixed(1) : "\u2014"}
            </text>
            <text
              x={cx}
              y={cy + 38}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={18}
              fontWeight={600}
              fill="#94A3B8"
              style={{ letterSpacing: 2 }}
            >
              / 10
            </text>
          </svg>
        </div>

        {/* Mini Spectrum strip (160px) */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 6,
            padding: "0 90px",
            position: "absolute",
            left: 0,
            right: 0,
            bottom: 130,
            height: 160,
          }}
        >
          {PILLAR_ORDER.map((k, i) => {
            const sc = scores[i]
            const hasData = fetchOk && scoreByKey[k] !== null && scoreByKey[k] !== undefined
            const width = hasData ? Math.max(2, (sc / 10) * 100) : 0
            return (
              <div
                key={k}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  height: 20,
                }}
              >
                <span
                  style={{
                    color: "#CBD5E1",
                    fontSize: 14,
                    fontWeight: 600,
                    width: 80,
                    display: "flex",
                    textTransform: "uppercase",
                    letterSpacing: 1,
                  }}
                >
                  {PILLAR_LABEL[k]}
                </span>
                <div
                  style={{
                    flex: 1,
                    height: 12,
                    background: "rgba(148,163,184,0.18)",
                    borderRadius: 6,
                    display: "flex",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: `${width}%`,
                      height: "100%",
                      background: PILLAR_COLOR[k],
                      display: "flex",
                    }}
                  />
                </div>
                <span
                  style={{
                    color: "#E2E8F0",
                    fontSize: 14,
                    fontWeight: 700,
                    width: 44,
                    display: "flex",
                    justifyContent: "flex-end",
                  }}
                >
                  {hasData ? sc.toFixed(1) : "\u2014"}
                </span>
              </div>
            )
          })}
        </div>

        {/* Bottom row (80px): verdict + url + disclaimer */}
        <div
          style={{
            position: "absolute",
            left: 70,
            right: 70,
            bottom: 40,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-end",
            height: 80,
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span
              style={{
                color: "#BFDBFE",
                fontSize: 20,
                fontWeight: 700,
                display: "flex",
                textTransform: "uppercase",
                letterSpacing: 1,
              }}
            >
              {verdictLabel}
            </span>
            <span style={{ color: "#60A5FA", fontSize: 22, fontWeight: 700, display: "flex" }}>
              yieldiq.in/prism/{cleanTicker}
            </span>
          </div>
          <span style={{ color: "#94A3B8", fontSize: 16, display: "flex" }}>
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
