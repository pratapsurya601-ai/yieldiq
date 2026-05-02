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

interface HexAxesPayload {
  // Backend canonical shape: { hex: { axes: { quality: {score, ...}, ... }, overall } }
  axes?: Record<string, PillarPayload>
  overall?: number
}

interface PrismPayload {
  ticker?: string
  company_name?: string
  verdict_label?: string
  verdict_band?: string
  overall?: number
  // Legacy/optional flattened pillars list. Modern backend ships scores
  // under `hex.axes[key].score`; keep `pillars` as a fallback for any
  // future flattened shape.
  pillars?: PillarPayload[]
  hex?: HexAxesPayload
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

  // CONSISTENCY FIX (radar=text on Prism pillars): the live page reads
  // `hex.axes[key].score` via adaptPrismResponse(); the OG card was
  // reading a non-existent `data.pillars[].score` and so every score
  // collapsed to 0 in the radar geometry. Pin both paths to the
  // canonical `hex.axes[k].score` field so the OG image matches the
  // live page (and the per-pillar text breakdown).
  const overallRaw = data.hex?.overall ?? data.overall ?? 0
  const overall = Math.max(0, Math.min(10, Number(overallRaw)))
  const company = (data.company_name || cleanTicker).toString().slice(0, 60)
  const verdictLabel = (data.verdict_label || "Analysis unavailable").slice(0, 40)

  // Build score map keyed by pillar key. Prefer the canonical `hex.axes`
  // shape; fall back to a flattened `pillars[]` for forward-compat.
  const scoreByKey: Record<string, number | null> = {}
  const axesPayload = data.hex?.axes
  if (axesPayload && typeof axesPayload === "object") {
    for (const k of Object.keys(axesPayload)) {
      const a = axesPayload[k]
      const s = a?.score
      const limited = a?.data_limited === true
      scoreByKey[k] =
        typeof s === "number" && !limited
          ? Math.max(0, Math.min(10, s))
          : null
    }
  } else {
    for (const p of data.pillars || []) {
      if (!p.key) continue
      scoreByKey[p.key] =
        typeof p.score === "number" && p.data_limited !== true
          ? Math.max(0, Math.min(10, p.score))
          : null
    }
  }
  const scores = PILLAR_ORDER.map((k) => {
    const v = scoreByKey[k]
    return typeof v === "number" ? v : 0
  })

  // Hexagon geometry for the Signature. SVG_TOP is the y-offset of the
  // SVG inside the root container — shared by the SVG itself and the
  // HTML overlays that replace <text> nodes (Satori in Next 16 rejects
  // <text> in SVG, so labels + numbers are positioned absolutely as
  // <div>s over the geometric shapes; see analysis/[ticker] for the
  // same pattern).
  const W = 1200
  const H = 1200
  const cx = 600
  const cy = 640
  const R = 300
  const SVG_TOP = 110

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

        {/* Signature — SVG holds ONLY geometric shapes; all typography
            is layered as absolutely-positioned HTML below. */}
        <svg
          width={W}
          height={720}
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
          {/* Vertex circles only — numbers rendered as HTML overlays */}
          {fetchOk &&
            PILLAR_ORDER.map((k, i) => {
              const [x, y] = vertex(i, scores[i])
              const color = PILLAR_COLOR[k] || scoreColor(scores[i])
              return <circle key={k} cx={x} cy={y} r={20} fill={color} />
            })}
          {/* Center composite disc — number overlaid as HTML */}
          <circle
            cx={cx}
            cy={cy}
            r={82}
            fill="rgba(15,23,42,0.9)"
            stroke="#60A5FA"
            strokeWidth={3}
          />
        </svg>

        {/* Axis labels — HTML overlays aligned to each hex vertex */}
        {PILLAR_ORDER.map((k, i) => {
          const [x, y] = labelPos[i]
          return (
            <div
              key={`lbl-${k}`}
              style={{
                position: "absolute",
                left: x - 80,
                top: SVG_TOP + y - 14,
                width: 160,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#E2E8F0",
                fontSize: 22,
                fontWeight: 700,
                letterSpacing: 1,
              }}
            >
              {PILLAR_LABEL[k].toUpperCase()}
            </div>
          )
        })}

        {/* Vertex score numbers — pinned to the same `scoreByKey` source
            the radar polygon uses, so the number under each vertex always
            matches the polygon's reach. Renders "—" for axes with no
            score (data_limited or missing) instead of a misleading "0.0". */}
        {fetchOk &&
          PILLAR_ORDER.map((k, i) => {
            const [x, y] = vertex(i, scores[i])
            const hasScore = scoreByKey[k] !== null && scoreByKey[k] !== undefined
            return (
              <div
                key={`num-${k}`}
                style={{
                  position: "absolute",
                  left: x - 26,
                  top: SVG_TOP + y - 12,
                  width: 52,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#ffffff",
                  fontSize: 18,
                  fontWeight: 800,
                }}
              >
                {hasScore ? scores[i].toFixed(1) : "—"}
              </div>
            )
          })}

        {/* Center composite number + "/ 10" caption */}
        <div
          style={{
            position: "absolute",
            left: cx - 90,
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
