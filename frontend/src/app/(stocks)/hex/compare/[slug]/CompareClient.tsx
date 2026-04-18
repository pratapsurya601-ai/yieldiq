"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { Fragment, useState } from "react"
import HexCompare from "@/components/hex/HexCompare"
import {
  HEX_AXIS_BLURB,
  HEX_AXIS_ORDER,
  type HexAxisKey,
  type HexResponse,
} from "@/lib/hex"

const AXIS_LABEL: Record<HexAxisKey, string> = {
  value: "Value",
  quality: "Quality",
  growth: "Growth",
  moat: "Moat",
  safety: "Safety",
  pulse: "Pulse",
}

function display(t: string): string {
  return t.replace(/\.(NS|BO)$/i, "")
}

function scoreClass(s: number): string {
  if (s >= 7) return "text-green-600"
  if (s >= 4) return "text-amber-600"
  return "text-red-600"
}

interface CompareClientProps {
  a: HexResponse
  b: HexResponse
  canonical: string
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
    router.push(`/hex/compare/${l}-vs-${r}`)
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

  const shareText = `${t1} vs ${t2} — Hex comparison on YieldIQ`
  const twitter = `https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(canonical)}`
  const whatsapp = `https://api.whatsapp.com/send?text=${encodeURIComponent(`${shareText} ${canonical}`)}`

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 sm:py-12">
      <nav className="text-xs text-gray-400 mb-6 flex items-center gap-1.5">
        <Link href="/" className="hover:text-gray-600">Home</Link>
        <span>/</span>
        <Link href={`/hex/${t1}`} className="hover:text-gray-600">Hex</Link>
        <span>/</span>
        <span className="text-gray-600 font-medium">{t1} vs {t2}</span>
      </nav>

      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 sm:p-8 mb-8">
        <h1 className="text-3xl sm:text-4xl font-black text-gray-900 mb-2">
          {t1} <span className="text-gray-400 font-medium">vs</span> {t2}
        </h1>
        <p className="text-gray-500 text-sm mb-6">
          6-axis hex overlay. Higher is stronger on each axis. Model estimate.
        </p>
        <div className="flex justify-center">
          <HexCompare a={a} b={b} size={380} />
        </div>
      </div>

      {/* Side-by-side table */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden mb-8">
        <div className="grid grid-cols-[1fr_auto_1fr] text-sm">
          <div className="p-4 font-bold text-blue-600 text-center border-b border-gray-100">
            {t1} &middot; {a.overall.toFixed(1)}/10
          </div>
          <div className="p-4 text-center text-xs text-gray-400 uppercase tracking-wider border-b border-gray-100">
            Axis
          </div>
          <div className="p-4 font-bold text-amber-600 text-center border-b border-gray-100">
            {t2} &middot; {b.overall.toFixed(1)}/10
          </div>
          {HEX_AXIS_ORDER.map((key) => {
            const av = a.axes[key]
            const bv = b.axes[key]
            return (
              <Fragment key={key}>
                <div className="p-4 border-t border-gray-100">
                  <div className={`text-lg font-bold font-mono ${scoreClass(av.score)}`}>
                    {av.score.toFixed(1)}
                  </div>
                  <div className="text-xs text-gray-500">{av.label}</div>
                  {av.why && <div className="text-[11px] text-gray-500 mt-1">{av.why}</div>}
                </div>
                <div className="p-4 border-t border-gray-100 flex flex-col items-center justify-center bg-gray-50">
                  <div className="text-xs font-bold text-gray-700 uppercase tracking-wider">
                    {AXIS_LABEL[key]}
                  </div>
                  <div className="text-[10px] text-gray-400 mt-1 text-center max-w-[160px] leading-tight">
                    {HEX_AXIS_BLURB[key]}
                  </div>
                </div>
                <div className="p-4 border-t border-gray-100 text-right">
                  <div className={`text-lg font-bold font-mono ${scoreClass(bv.score)}`}>
                    {bv.score.toFixed(1)}
                  </div>
                  <div className="text-xs text-gray-500">{bv.label}</div>
                  {bv.why && <div className="text-[11px] text-gray-500 mt-1">{bv.why}</div>}
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
