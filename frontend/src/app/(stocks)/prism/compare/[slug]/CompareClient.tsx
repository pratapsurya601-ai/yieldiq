"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { Fragment, useState } from "react"
import type { PillarKey, PrismData } from "@/components/prism/types"
import { PRISM_PILLAR_ORDER } from "@/lib/prism"

const PILLAR_LABEL: Record<PillarKey, string> = {
  pulse: "Pulse",
  quality: "Quality",
  moat: "Moat",
  safety: "Safety",
  growth: "Growth",
  value: "Value",
}

// Overlay colors — brand blue for A, amber for B (spec).
const COLOR_A = "#3B82F6"
const COLOR_B = "#F59E0B"

function display(t: string): string {
  return t.replace(/\.(NS|BO)$/i, "")
}

function scoreClass(s: number): string {
  if (s >= 7) return "text-green-600"
  if (s >= 4) return "text-amber-600"
  return "text-red-600"
}

interface CompareClientProps {
  a: PrismData
  b: PrismData
  canonical: string
}

/**
 * Overlay two hexagonal Signatures on one SVG. Pure geometry — mirrors the
 * Signature component's vertex math so the overlay lines up with the
 * single-stock prism view.
 */
function SignatureOverlay({
  a,
  b,
  size,
  tA,
  tB,
}: {
  a: PrismData
  b: PrismData
  size: number
  tA: string
  tB: string
}) {
  const cx = size / 2
  const cy = size / 2
  const R = size / 2 - 48

  const scoreMap = (d: PrismData) => {
    const m: Record<PillarKey, number> = {
      pulse: 0, quality: 0, moat: 0, safety: 0, growth: 0, value: 0,
    }
    for (const p of d.pillars) {
      m[p.key] = typeof p.score === "number" ? Math.max(0, Math.min(10, p.score)) : 0
    }
    return m
  }
  const sa = scoreMap(a)
  const sb = scoreMap(b)

  const vertex = (i: number, v: number): [number, number] => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / 6
    const r = (v / 10) * R
    return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)]
  }
  const poly = (scores: number[]) =>
    scores.map((s, i) => vertex(i, s).join(",")).join(" ")
  const ring = (v: number) =>
    Array.from({ length: 6 }, (_, i) => vertex(i, v).join(",")).join(" ")

  const scoresA = PRISM_PILLAR_ORDER.map((k) => sa[k])
  const scoresB = PRISM_PILLAR_ORDER.map((k) => sb[k])

  const labelPos = PRISM_PILLAR_ORDER.map((_, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / 6
    const rr = R + 28
    return [cx + rr * Math.cos(angle), cy + rr * Math.sin(angle)] as [number, number]
  })

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {[2, 4, 6, 8, 10].map((v) => (
        <polygon
          key={v}
          points={ring(v)}
          fill="none"
          stroke="rgba(100,116,139,0.2)"
          strokeWidth={1}
        />
      ))}
      {PRISM_PILLAR_ORDER.map((_, i) => {
        const [x, y] = vertex(i, 10)
        return (
          <line
            key={i}
            x1={cx}
            y1={cy}
            x2={x}
            y2={y}
            stroke="rgba(100,116,139,0.2)"
            strokeWidth={1}
          />
        )
      })}
      <polygon
        points={poly(scoresA)}
        fill={COLOR_A}
        fillOpacity={0.22}
        stroke={COLOR_A}
        strokeWidth={2.5}
      />
      <polygon
        points={poly(scoresB)}
        fill={COLOR_B}
        fillOpacity={0.22}
        stroke={COLOR_B}
        strokeWidth={2.5}
      />
      {PRISM_PILLAR_ORDER.map((k, i) => {
        const [x, y] = labelPos[i]
        return (
          <text
            key={k}
            x={x}
            y={y}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={11}
            fontWeight={700}
            fill="#475569"
          >
            {PILLAR_LABEL[k].toUpperCase()}
          </text>
        )
      })}
      {/* Legend */}
      <g>
        <rect x={12} y={12} width={14} height={14} rx={3} fill={COLOR_A} />
        <text x={32} y={24} fontSize={12} fontWeight={700} fill="#334155">{tA}</text>
        <rect x={12} y={32} width={14} height={14} rx={3} fill={COLOR_B} />
        <text x={32} y={44} fontSize={12} fontWeight={700} fill="#334155">{tB}</text>
      </g>
    </svg>
  )
}

/**
 * Split-mirror Spectrum. One row per pillar: A's bar extends LEFT from the
 * center axis label; B's bar extends RIGHT. Reads top-to-bottom.
 */
function SplitMirrorSpectrum({
  a,
  b,
  tA,
  tB,
}: {
  a: PrismData
  b: PrismData
  tA: string
  tB: string
}) {
  const byKeyA = new Map(a.pillars.map((p) => [p.key, p]))
  const byKeyB = new Map(b.pillars.map((p) => [p.key, p]))

  return (
    <div className="flex flex-col">
      {/* Header row */}
      <div className="grid grid-cols-[1fr_110px_1fr] items-end pb-3 border-b border-gray-100">
        <div className="text-right pr-3">
          <div className="text-sm font-bold" style={{ color: COLOR_A }}>{tA}</div>
          <div className="text-[11px] text-gray-500 font-mono">
            {a.overall.toFixed(1)}/10 &middot; {a.verdict_label}
          </div>
        </div>
        <div className="text-center text-[10px] text-gray-400 uppercase tracking-wider">
          Pillar
        </div>
        <div className="text-left pl-3">
          <div className="text-sm font-bold" style={{ color: COLOR_B }}>{tB}</div>
          <div className="text-[11px] text-gray-500 font-mono">
            {b.overall.toFixed(1)}/10 &middot; {b.verdict_label}
          </div>
        </div>
      </div>

      {PRISM_PILLAR_ORDER.map((key) => {
        const pa = byKeyA.get(key)
        const pb = byKeyB.get(key)
        const sa =
          pa && typeof pa.score === "number" ? Math.max(0, Math.min(10, pa.score)) : null
        const sb =
          pb && typeof pb.score === "number" ? Math.max(0, Math.min(10, pb.score)) : null
        const wa = sa !== null ? (sa / 10) * 100 : 0
        const wb = sb !== null ? (sb / 10) * 100 : 0
        return (
          <div
            key={key}
            className="grid grid-cols-[1fr_110px_1fr] items-center py-3 border-b border-gray-50"
          >
            {/* Left bar: extends right-to-left, anchored at the right */}
            <div className="flex items-center justify-end gap-3">
              <span className="text-xs font-mono tabular-nums text-gray-600 w-8 text-right">
                {sa !== null ? sa.toFixed(1) : "\u2014"}
              </span>
              <div className="flex-1 h-3 bg-gray-100 rounded-full overflow-hidden relative max-w-[240px]">
                <div
                  className="absolute top-0 right-0 h-full rounded-full"
                  style={{ width: `${wa}%`, backgroundColor: COLOR_A }}
                />
              </div>
            </div>
            {/* Center label */}
            <div className="text-center">
              <div className="text-xs font-bold text-gray-700 uppercase tracking-wider">
                {PILLAR_LABEL[key]}
              </div>
            </div>
            {/* Right bar: extends left-to-right, anchored at the left */}
            <div className="flex items-center gap-3">
              <div className="flex-1 h-3 bg-gray-100 rounded-full overflow-hidden relative max-w-[240px]">
                <div
                  className="absolute top-0 left-0 h-full rounded-full"
                  style={{ width: `${wb}%`, backgroundColor: COLOR_B }}
                />
              </div>
              <span className="text-xs font-mono tabular-nums text-gray-600 w-8">
                {sb !== null ? sb.toFixed(1) : "\u2014"}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function CompareClient({ a, b, canonical }: CompareClientProps) {
  const router = useRouter()
  const t1 = display(a.ticker)
  const t2 = display(b.ticker)

  const [left, setLeft] = useState(t1)
  const [right, setRight] = useState(t2)
  const [copied, setCopied] = useState(false)

  const changeStocks = () => {
    const l = left.trim().toUpperCase().replace(/\.(NS|BO)$/i, "")
    const r = right.trim().toUpperCase().replace(/\.(NS|BO)$/i, "")
    if (!l || !r) return
    router.push(`/prism/compare/${l}-vs-${r}`)
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(canonical)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // ignore
    }
  }

  const shareText = `${t1} vs ${t2} \u2014 Prism comparison on YieldIQ`
  const twitter = `https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(canonical)}`
  const whatsapp = `https://api.whatsapp.com/send?text=${encodeURIComponent(`${shareText} ${canonical}`)}`

  const byKeyA = new Map(a.pillars.map((p) => [p.key, p]))
  const byKeyB = new Map(b.pillars.map((p) => [p.key, p]))

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 sm:py-12">
      <nav className="text-xs text-gray-400 mb-6 flex items-center gap-1.5">
        <Link href="/" className="hover:text-gray-600">Home</Link>
        <span>/</span>
        <Link href={`/prism/${t1}`} className="hover:text-gray-600">Prism</Link>
        <span>/</span>
        <span className="text-gray-600 font-medium">{t1} vs {t2}</span>
      </nav>

      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 sm:p-8 mb-8">
        <h1 className="text-3xl sm:text-4xl font-serif font-black text-gray-900 mb-2">
          {t1} <span className="text-gray-400 font-medium">vs</span> {t2}
        </h1>
        <p className="text-gray-500 text-sm mb-6">
          6-pillar prism overlay. Higher is stronger on each pillar. Model estimate.
        </p>
        <div className="flex justify-center">
          <SignatureOverlay a={a} b={b} size={420} tA={t1} tB={t2} />
        </div>
      </div>

      {/* Split-mirror Spectrum */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8">
        <h2 className="text-sm font-bold text-gray-900 uppercase tracking-wider mb-4">
          Pillar spectrum
        </h2>
        <SplitMirrorSpectrum a={a} b={b} tA={t1} tB={t2} />
      </div>

      {/* Per-axis delta table */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden mb-8">
        <div className="grid grid-cols-[1fr_auto_1fr_auto] text-sm">
          <div className="p-4 font-bold text-center border-b border-gray-100" style={{ color: COLOR_A }}>
            {t1}
          </div>
          <div className="p-4 text-center text-xs text-gray-400 uppercase tracking-wider border-b border-gray-100">
            Pillar
          </div>
          <div className="p-4 font-bold text-center border-b border-gray-100" style={{ color: COLOR_B }}>
            {t2}
          </div>
          <div className="p-4 text-center text-xs text-gray-400 uppercase tracking-wider border-b border-gray-100">
            Δ
          </div>
          {PRISM_PILLAR_ORDER.map((key) => {
            const pa = byKeyA.get(key)
            const pb = byKeyB.get(key)
            const sa = pa && typeof pa.score === "number" ? pa.score : null
            const sb = pb && typeof pb.score === "number" ? pb.score : null
            const delta = sa !== null && sb !== null ? sa - sb : null
            return (
              <Fragment key={key}>
                <div className="p-4 border-t border-gray-100 text-right">
                  <div className={`text-lg font-bold font-mono ${sa !== null ? scoreClass(sa) : "text-gray-400"}`}>
                    {sa !== null ? sa.toFixed(1) : "\u2014"}
                  </div>
                  {pa?.label && <div className="text-xs text-gray-500">{pa.label}</div>}
                </div>
                <div className="p-4 border-t border-gray-100 flex flex-col items-center justify-center bg-gray-50 min-w-[100px]">
                  <div className="text-xs font-bold text-gray-700 uppercase tracking-wider">
                    {PILLAR_LABEL[key]}
                  </div>
                </div>
                <div className="p-4 border-t border-gray-100 text-left">
                  <div className={`text-lg font-bold font-mono ${sb !== null ? scoreClass(sb) : "text-gray-400"}`}>
                    {sb !== null ? sb.toFixed(1) : "\u2014"}
                  </div>
                  {pb?.label && <div className="text-xs text-gray-500">{pb.label}</div>}
                </div>
                <div className="p-4 border-t border-gray-100 text-center min-w-[80px]">
                  <div className={`text-sm font-mono font-bold ${
                    delta === null
                      ? "text-gray-400"
                      : delta > 0
                        ? "text-blue-600"
                        : delta < 0
                          ? "text-amber-600"
                          : "text-gray-500"
                  }`}>
                    {delta === null
                      ? "\u2014"
                      : `${delta > 0 ? "+" : ""}${delta.toFixed(1)}`}
                  </div>
                </div>
              </Fragment>
            )
          })}
        </div>
      </div>

      {/* Change stocks */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8">
        <h2 className="text-lg font-bold text-gray-900 mb-3">Change stocks</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            changeStocks()
          }}
          className="grid grid-cols-1 sm:grid-cols-[1fr_auto_1fr_auto] gap-3 items-center"
        >
          <input
            value={left}
            onChange={(e) => setLeft(e.target.value)}
            className="border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Ticker 1"
          />
          <span className="text-gray-400 text-sm text-center">vs</span>
          <input
            value={right}
            onChange={(e) => setRight(e.target.value)}
            className="border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Ticker 2"
          />
          <button
            type="submit"
            className="bg-blue-600 text-white text-sm font-semibold px-5 py-2.5 rounded-xl hover:bg-blue-500 transition"
          >
            Compare
          </button>
        </form>
      </div>

      {/* Share */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-8">
        <h2 className="text-lg font-bold text-gray-900 mb-3">Share</h2>
        <div className="flex flex-wrap gap-3">
          <a
            href={twitter}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 bg-gray-900 text-white text-sm font-semibold px-4 py-2 rounded-xl hover:bg-gray-700 transition"
          >
            Share on X
          </a>
          <a
            href={whatsapp}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 bg-green-600 text-white text-sm font-semibold px-4 py-2 rounded-xl hover:bg-green-500 transition"
          >
            WhatsApp
          </a>
          <button
            type="button"
            onClick={copy}
            className="inline-flex items-center gap-2 bg-blue-600 text-white text-sm font-semibold px-4 py-2 rounded-xl hover:bg-blue-500 transition"
          >
            {copied ? "Copied!" : "Copy link"}
          </button>
        </div>
      </div>

      {/* CTA */}
      <div className="bg-gradient-to-r from-blue-600 to-cyan-500 rounded-2xl p-8 text-center text-white mb-8">
        <h2 className="text-xl font-bold mb-2">Get the full analysis</h2>
        <p className="text-blue-100 text-sm mb-4">
          Unlock interactive DCF, sensitivity, peer ratios and AI summaries.
        </p>
        <Link
          href="/signup"
          className="inline-block bg-white text-blue-700 font-bold px-8 py-3 rounded-xl hover:bg-blue-50 transition"
        >
          Create a free account &rarr;
        </Link>
      </div>

      <p className="text-[10px] text-gray-400 text-center leading-relaxed">
        Model estimate. Not investment advice.
        YieldIQ is not registered with SEBI as an investment adviser or research analyst.
        Past performance does not guarantee future results.
      </p>
    </div>
  )
}
