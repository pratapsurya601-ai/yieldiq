"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import Hex from "@/components/hex/Hex"
import HexExplainer from "@/components/hex/HexExplainer"
import {
  fetchPortfolioHex,
  fetchSectorMedian,
  HEX_AXIS_ORDER,
  type HexAxisKey,
  type HexResponse,
  type PortfolioHolding,
} from "@/lib/hex"

type Holding = {
  ticker: string
  current_value?: number
  invested_value?: number
}

interface Props {
  holdings: Holding[]
}

const AXIS_LABEL: Record<HexAxisKey, string> = {
  value: "Value",
  quality: "Quality",
  growth: "Growth",
  moat: "Moat",
  safety: "Safety",
  pulse: "Pulse",
}

function useViewportSize() {
  // SSR-safe — just pick based on window width on first client render.
  const [size, setSize] = useState<number>(() => {
    if (typeof window === "undefined") return 280
    return window.innerWidth < 640 ? 220 : 280
  })
  useEffect(() => {
    if (typeof window === "undefined") return
    const onResize = () => setSize(window.innerWidth < 640 ? 220 : 280)
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [])
  return size
}

function HexSkeleton({ size }: { size: number }) {
  return (
    <div
      className="skeleton rounded-full"
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  )
}

export default function PortfolioHex({ holdings }: Props) {
  const size = useViewportSize()
  const [overlayNifty, setOverlayNifty] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const [explainAxis, setExplainAxis] = useState<HexAxisKey | null>(null)

  const payload: PortfolioHolding[] = useMemo(() => {
    return holdings
      .filter((h) => h.ticker)
      .map((h) => {
        const w = Number(h.current_value ?? h.invested_value ?? 0)
        return { ticker: h.ticker, weight: Number.isFinite(w) && w > 0 ? w : 1 }
      })
  }, [holdings])

  const enabled = payload.length >= 3

  const {
    data,
    isLoading,
    isError,
  } = useQuery<HexResponse>({
    queryKey: ["portfolio-hex", payload.map((p) => `${p.ticker}:${p.weight.toFixed(2)}`).join("|")],
    queryFn: () => fetchPortfolioHex(payload),
    enabled,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const { data: sectorMedian } = useQuery({
    queryKey: ["hex-sector-median", "general"],
    queryFn: () => fetchSectorMedian("general"),
    enabled: overlayNifty && !!data,
    staleTime: 60 * 60 * 1000,
  })

  // Build a sector overlay by injecting sector_medians into the response.
  // NOTE: must be called unconditionally, before any early returns.
  const displayData: HexResponse | undefined = useMemo(() => {
    if (!data) return undefined
    if (!overlayNifty || !sectorMedian?.medians) return data
    return { ...data, sector_medians: sectorMedian.medians }
  }, [data, overlayNifty, sectorMedian])

  // Empty state: fewer than 3 holdings.
  if (!enabled) {
    return (
      <section
        aria-labelledby="portfolio-hex-heading"
        className="bg-surface rounded-2xl border border-border p-5"
      >
        <h2
          id="portfolio-hex-heading"
          className="text-base font-bold text-ink mb-1"
        >
          Your Portfolio Hex
        </h2>
        <p className="text-xs text-caption mb-4">
          Add at least 3 holdings to see your Portfolio Hex. Model estimate. Not investment advice.
        </p>
        <Link
          href="/portfolio/import"
          className="inline-flex items-center justify-center min-h-[44px] bg-brand text-white text-sm font-semibold px-4 py-2 rounded-lg hover:opacity-90 active:scale-[0.98] transition"
        >
          Import holdings &rarr;
        </Link>
      </section>
    )
  }

  // Error state: small banner, never crashes parent.
  if (isError) {
    return (
      <section
        aria-labelledby="portfolio-hex-heading"
        className="bg-surface rounded-2xl border border-border p-5"
      >
        <h2
          id="portfolio-hex-heading"
          className="text-base font-bold text-ink mb-1"
        >
          Your Portfolio Hex
        </h2>
        <div
          role="alert"
          className="mt-2 text-sm text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2"
        >
          Couldn&apos;t compute your Portfolio Hex right now. Please try again in a moment.
        </div>
      </section>
    )
  }

  // Strongest / weakest axis.
  const ranked = displayData
    ? HEX_AXIS_ORDER.map((k) => ({ key: k, score: displayData.axes[k].score }))
        .slice()
        .sort((a, b) => b.score - a.score)
    : []
  const strongest = ranked[0]
  const weakest = ranked[ranked.length - 1]

  return (
    <section
      aria-labelledby="portfolio-hex-heading"
      className="bg-surface rounded-2xl border border-border p-5"
    >
      <div className="flex items-start justify-between gap-3 mb-1">
        <h2
          id="portfolio-hex-heading"
          className="text-base font-bold text-ink"
        >
          Your Portfolio Hex
        </h2>
        <button
          type="button"
          onClick={() => setShareOpen(true)}
          className="inline-flex items-center justify-center min-h-[36px] text-xs font-semibold text-brand hover:opacity-80 px-2"
          aria-label="Share my Portfolio Hex"
        >
          Share &rarr;
        </button>
      </div>
      <p className="text-xs text-caption mb-4">
        Weighted average of your {payload.length} holding{payload.length === 1 ? "" : "s"}. Model estimate. Not investment advice.
      </p>

      <div className="flex flex-col items-center">
        {isLoading || !displayData ? (
          <>
            <HexSkeleton size={size} />
            <p className="mt-3 text-xs text-caption">Computing your Portfolio Hex...</p>
          </>
        ) : (
          <>
            <Hex
              data={displayData}
              size={size}
              sectorOverlay={overlayNifty}
              onAxisTap={(k) => setExplainAxis(k)}
            />
            {strongest && weakest && (
              <p className="mt-3 text-xs text-body text-center">
                Overall:{" "}
                <span className="font-bold text-ink">
                  {displayData.overall.toFixed(1)}/10
                </span>
                {" · "}Strongest axis:{" "}
                <span className="font-semibold">{AXIS_LABEL[strongest.key]}</span>
                {" · "}Weakest:{" "}
                <span className="font-semibold">{AXIS_LABEL[weakest.key]}</span>
              </p>
            )}
          </>
        )}
      </div>

      {/* Compare toggle */}
      <div className="mt-4 flex items-center justify-center">
        <label className="inline-flex items-center gap-2 cursor-pointer select-none min-h-[44px] px-2">
          <input
            type="checkbox"
            checked={overlayNifty}
            onChange={(e) => setOverlayNifty(e.target.checked)}
            className="w-4 h-4 accent-blue-600"
            aria-label="Compare with Nifty 50 sector median"
          />
          <span className="text-xs font-medium text-body">
            Compare with Nifty 50 median
          </span>
        </label>
      </div>

      {/* Explainer */}
      {displayData && (
        <HexExplainer
          open={explainAxis !== null}
          axis={explainAxis}
          data={displayData}
          onClose={() => setExplainAxis(null)}
        />
      )}

      {/* Share modal */}
      {shareOpen && (
        <div
          className="fixed inset-0 z-50 flex items-end md:items-center justify-center"
          role="dialog"
          aria-modal="true"
          aria-labelledby="share-hex-title"
        >
          <button
            type="button"
            aria-label="Close"
            onClick={() => setShareOpen(false)}
            className="absolute inset-0 bg-black/40"
          />
          <div className="relative bg-surface rounded-t-2xl md:rounded-2xl border border-border p-5 w-full md:max-w-md mx-auto max-h-[90vh] overflow-y-auto">
            <div className="flex items-start justify-between">
              <h3 id="share-hex-title" className="text-base font-bold text-ink">
                Share your Portfolio Hex
              </h3>
              <button
                type="button"
                onClick={() => setShareOpen(false)}
                aria-label="Close"
                className="inline-flex items-center justify-center min-w-[44px] min-h-[44px] text-caption hover:text-body"
              >
                &times;
              </button>
            </div>
            <p className="text-xs text-caption mt-1">
              Model estimate. Not investment advice.
            </p>
            <div className="mt-4 flex justify-center">
              {displayData && (
                <Hex data={displayData} size={size} sectorOverlay={overlayNifty} />
              )}
            </div>
            <p className="mt-4 text-sm text-body">
              Take a screenshot of this Hex to share on social or with friends. Full share tooling is coming soon.
            </p>
            <button
              type="button"
              onClick={() => setShareOpen(false)}
              className="mt-4 w-full inline-flex items-center justify-center min-h-[44px] bg-brand text-white text-sm font-semibold px-4 py-2 rounded-lg hover:opacity-90 active:scale-[0.98] transition"
            >
              Got it
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

