"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import Prism from "@/components/prism/Prism"
import PrismSkeleton from "@/components/prism/PrismSkeleton"
import {
  fetchPortfolioHex,
  fetchSectorMedian,
  type HexAxisKey,
  type HexResponse,
  type PortfolioHolding,
} from "@/lib/hex"
import { computeRefraction } from "@/lib/prism"
import type {
  Pillar,
  PillarKey,
  PrismData,
  VerdictBand,
} from "@/components/prism/types"

type Holding = {
  ticker: string
  current_value?: number
  invested_value?: number
}

interface Props {
  holdings: Holding[]
}

const AXIS_KEYS: HexAxisKey[] = [
  "value",
  "quality",
  "growth",
  "moat",
  "safety",
  "pulse",
]

const PILLAR_LABEL: Record<PillarKey, string> = {
  value: "Value",
  quality: "Quality",
  growth: "Growth",
  moat: "Moat",
  safety: "Safety",
  pulse: "Pulse",
}

/**
 * Score-band templates for the Strongest-lens readout. Factual only — never
 * prescriptive. Branches on score band so a "moderate" strongest pillar
 * doesn't overclaim.
 */
function strongestCopy(key: PillarKey, score: number): string {
  const strong = score >= 7
  switch (key) {
    case "quality":
      return strong
        ? "Your holdings lean on high return-on-capital businesses."
        : "Quality is your most consistent lens — profitability is steady across holdings."
    case "value":
      return strong
        ? "Your holdings trade below model fair values on average."
        : "Value is your best lens — holdings are priced near model fair values on average."
    case "growth":
      return strong
        ? "Your holdings show above-median revenue and earnings expansion."
        : "Growth is your best lens — expansion is the most consistent signal across holdings."
    case "moat":
      return strong
        ? "Your holdings tilt toward businesses with durable competitive advantages."
        : "Moat is your best lens — holdings score near the market median for defensibility."
    case "safety":
      return strong
        ? "Your holdings carry durable balance sheets with low leverage on average."
        : "Safety is your best lens — balance-sheet quality is the most consistent signal."
    case "pulse":
      return strong
        ? "Your holdings carry positive near-term momentum on average."
        : "Pulse is your best lens — near-term momentum is the most consistent signal."
  }
}

/**
 * Score-band templates for the Weakest-lens readout. Strictly factual — no
 * "sell", "trim", "add more", or directional action language.
 */
function weakestCopy(key: PillarKey, score: number): string {
  const weak = score < 4
  switch (key) {
    case "value":
      return weak
        ? "Your holdings are priced above model fair values on average."
        : "Value is your lowest lens — holdings are priced near the upper end of model fair values."
    case "quality":
      return weak
        ? "Return on capital is below the market median across holdings on average."
        : "Quality is your lowest lens — return on capital sits near the market median."
    case "growth":
      return weak
        ? "Revenue and earnings expansion is below the market median across holdings."
        : "Growth is your lowest lens — expansion sits near the market median."
    case "moat":
      return weak
        ? "Competitive moats across holdings score below the market median."
        : "Moat is your lowest lens — defensibility scores near the market median."
    case "safety":
      return weak
        ? "Balance-sheet leverage is above the market median across holdings."
        : "Safety is your lowest lens — leverage sits near the market median."
    case "pulse":
      return weak
        ? "Near-term momentum is negative across holdings on average."
        : "Pulse is your lowest lens — momentum sits near neutral across holdings."
  }
}

function deriveVerdict(overall: number): {
  band: VerdictBand
  label: string
} {
  if (overall >= 7.5) return { band: "deepValue", label: "Durable overall profile" }
  if (overall >= 5) return { band: "fair", label: "Balanced profile" }
  return { band: "overvalued", label: "Needs attention" }
}

/**
 * Maps the portfolio hex aggregate response to PrismData. The hex payload
 * already has 6 axes on 0..10 plus `overall`; we synthesize verdict from the
 * overall and compute refraction locally. Pulse velocity is pinned to 0.33Hz
 * (slow ambient breathing) since a portfolio aggregate doesn't have a single
 * "pulse rate" — the individual stocks do.
 */
function hexToPrismData(hex: HexResponse, holdingCount: number): PrismData {
  const pillars: Pillar[] = AXIS_KEYS.map((k) => {
    const axis = hex.axes[k]
    // FIX day2-#13: defend against a missing axis payload or a backend
    // "—" label slipping in as the lens verdict. Pillar axis NAMES (Value,
    // Quality, Pulse, ...) are rendered via a hard-coded map in
    // Signature/Spectrum keyed on `key`, so the axis *name* is always
    // safe. But `label` is used in PillarExplainer — fall back to the
    // pillar name so it never renders a literal dash.
    const pillarKey = k as PillarKey
    const safeLabel =
      axis && typeof axis.label === "string" && axis.label.trim() && axis.label.trim() !== "\u2014"
        ? axis.label
        : PILLAR_LABEL[pillarKey]
    return {
      key: pillarKey,
      score: axis && axis.data_limited ? null : (axis?.score ?? null),
      label: safeLabel,
      why: (axis && typeof axis.why === "string" ? axis.why : "Data not available."),
      data_limited: axis ? !!axis.data_limited : true,
      weight: 1 / 6,
    }
  })
  const verdict = deriveVerdict(hex.overall)
  return {
    ticker: "PORTFOLIO",
    company_name: `Your Portfolio (${holdingCount} holdings)`,
    verdict_band: verdict.band,
    verdict_label: verdict.label,
    pillars,
    overall: hex.overall,
    refraction_index: computeRefraction(pillars),
    pulse_velocity_hz: 0.33,
    sector_medians: hex.sector_medians as PrismData["sector_medians"],
    disclaimer:
      hex.disclaimer ||
      "Model estimate based on a weighted aggregate of your holdings. Not investment advice.",
  }
}

function useViewportSize() {
  const [size, setSize] = useState<number>(() => {
    if (typeof window === "undefined") return 300
    return window.innerWidth < 640 ? 220 : 300
  })
  useEffect(() => {
    if (typeof window === "undefined") return
    const onResize = () =>
      setSize(window.innerWidth < 640 ? 220 : 300)
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [])
  return size
}

export default function PortfolioPrism({ holdings }: Props) {
  const size = useViewportSize()
  const [overlayNifty, setOverlayNifty] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)

  const payload: PortfolioHolding[] = useMemo(() => {
    return holdings
      .filter((h) => h.ticker)
      .map((h) => {
        const w = Number(h.current_value ?? h.invested_value ?? 0)
        return {
          ticker: h.ticker,
          weight: Number.isFinite(w) && w > 0 ? w : 1,
        }
      })
  }, [holdings])

  const enabled = payload.length >= 3

  const { data: hexData, isLoading, isError } = useQuery<HexResponse>({
    queryKey: [
      "portfolio-hex",
      payload.map((p) => `${p.ticker}:${p.weight.toFixed(2)}`).join("|"),
    ],
    queryFn: () => fetchPortfolioHex(payload),
    enabled,
    staleTime: 60_000,
    retry: 1,
  })

  const { data: sectorMedian } = useQuery({
    queryKey: ["hex-sector-median", "general"],
    queryFn: () => fetchSectorMedian("general"),
    enabled: overlayNifty && !!hexData,
    staleTime: 60 * 60 * 1000,
  })

  const prismData: PrismData | undefined = useMemo(() => {
    if (!hexData) return undefined
    const base = hexToPrismData(hexData, payload.length)
    if (overlayNifty && sectorMedian?.medians) {
      return { ...base, sector_medians: sectorMedian.medians }
    }
    return base
  }, [hexData, overlayNifty, sectorMedian, payload.length])

  // Rank pillars for strongest/weakest readout (ignore data_limited axes).
  const ranked = useMemo(() => {
    if (!prismData) return []
    return prismData.pillars
      .filter(
        (p): p is Pillar & { score: number } =>
          typeof p.score === "number" && !p.data_limited,
      )
      .slice()
      .sort((a, b) => b.score - a.score)
  }, [prismData])
  const strongest = ranked[0]
  const weakest = ranked[ranked.length - 1]

  // Empty state
  if (!enabled) {
    return (
      <section
        aria-labelledby="portfolio-prism-heading"
        className="rounded-2xl border border-border p-5"
        style={{ background: "var(--color-surface)" }}
      >
        <h2
          id="portfolio-prism-heading"
          className="text-base font-bold mb-1"
          style={{ color: "var(--color-text)" }}
        >
          Your Portfolio Prism
        </h2>
        <p
          className="text-xs mb-4"
          style={{ color: "var(--color-caption)" }}
        >
          Add at least 3 holdings to see your Portfolio Prism. Model estimate. Not investment advice.
        </p>
        <Link
          href="/portfolio/import"
          className="inline-flex items-center justify-center min-h-[44px] text-sm font-semibold px-4 py-2 rounded-lg active:scale-[0.98] transition"
          style={{
            background: "var(--color-brand)",
            color: "var(--color-bg)",
          }}
        >
          Import holdings &rarr;
        </Link>
      </section>
    )
  }

  // Error state
  if (isError) {
    return (
      <section
        aria-labelledby="portfolio-prism-heading"
        className="rounded-2xl border border-border p-5"
        style={{ background: "var(--color-surface)" }}
      >
        <h2
          id="portfolio-prism-heading"
          className="text-base font-bold mb-1"
          style={{ color: "var(--color-text)" }}
        >
          Your Portfolio Prism
        </h2>
        <div
          role="alert"
          className="mt-2 text-sm rounded-lg px-3 py-2 border"
          style={{
            color: "var(--color-warning)",
            background: "var(--color-warning-bg, transparent)",
            borderColor: "var(--color-warning)",
          }}
        >
          Couldn&apos;t compute your Portfolio Prism right now. Try again shortly.
        </div>
      </section>
    )
  }

  return (
    <section
      aria-labelledby="portfolio-prism-heading"
      className="rounded-2xl border border-border p-5"
      style={{ background: "var(--color-surface)" }}
    >
      <div className="flex items-start justify-between gap-3 mb-1">
        <h2
          id="portfolio-prism-heading"
          className="text-base font-bold"
          style={{ color: "var(--color-text)" }}
        >
          Your Portfolio Prism
        </h2>
        <button
          type="button"
          onClick={() => setShareOpen(true)}
          className="inline-flex items-center justify-center min-h-[36px] text-xs font-semibold px-2"
          style={{ color: "var(--color-brand)" }}
          aria-label="Share my Portfolio Prism"
        >
          Share &rarr;
        </button>
      </div>
      <p
        className="text-xs mb-4"
        style={{ color: "var(--color-caption)" }}
      >
        Weighted average of your {payload.length} holding
        {payload.length === 1 ? "" : "s"}. Model estimate.
      </p>

      {/* Prism visual wrapper — width/height constrained to `size` so the
          inner SVG's `aspectRatio: 1/1` can never blow up the layout on
          wide desktop viewports. Previously the Prism root div had
          `width: 100%` with `maxWidth: size`, which in an items-center
          flex-column caused the browser to reserve full parent width
          BEFORE applying maxWidth — leaving a huge blank square below
          the actual rendered hex. Pinning the wrapper here keeps the
          section compact. */}
      <div className="flex flex-col items-center">
        <div style={{ width: size, maxWidth: "100%" }}>
          {isLoading || !prismData ? (
            <>
              <PrismSkeleton size={size} />
              <p
                className="mt-3 text-xs text-center"
                style={{ color: "var(--color-caption)" }}
              >
                Computing your Portfolio Prism...
              </p>
            </>
          ) : (
            <Prism
              data={prismData}
              size={size}
              defaultMode="signature"
              sectorOverlay={overlayNifty}
            />
          )}
        </div>
      </div>

      {/* Strongest / Weakest lens cards */}
      {prismData && strongest && weakest && strongest.key !== weakest.key && (
        <div className="mt-5 grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div
            className="rounded-xl border p-4"
            style={{
              borderColor: "var(--color-success)",
              background: "var(--color-surface)",
            }}
          >
            <p
              className="text-[10px] uppercase tracking-wider font-bold mb-1"
              style={{ color: "var(--color-success)" }}
            >
              Strongest lens
            </p>
            <p
              className="text-sm font-bold mb-1"
              style={{ color: "var(--color-text)" }}
            >
              {PILLAR_LABEL[strongest.key]} &middot; {strongest.score != null ? strongest.score.toFixed(1) : "\u2014"}
            </p>
            <p
              className="text-xs"
              style={{ color: "var(--color-caption)" }}
            >
              {strongestCopy(strongest.key, strongest.score)}
            </p>
          </div>
          <div
            className="rounded-xl border p-4"
            style={{
              borderColor: "var(--color-warning)",
              background: "var(--color-surface)",
            }}
          >
            <p
              className="text-[10px] uppercase tracking-wider font-bold mb-1"
              style={{ color: "var(--color-warning)" }}
            >
              Weakest lens
            </p>
            <p
              className="text-sm font-bold mb-1"
              style={{ color: "var(--color-text)" }}
            >
              {PILLAR_LABEL[weakest.key]} &middot; {weakest.score != null ? weakest.score.toFixed(1) : "\u2014"}
            </p>
            <p
              className="text-xs"
              style={{ color: "var(--color-caption)" }}
            >
              {weakestCopy(weakest.key, weakest.score)}
            </p>
          </div>
        </div>
      )}

      {/* Compare toggle */}
      <div className="mt-4 flex items-center justify-center">
        <label className="inline-flex items-center gap-2 cursor-pointer select-none min-h-[44px] px-2">
          <input
            type="checkbox"
            checked={overlayNifty}
            onChange={(e) => setOverlayNifty(e.target.checked)}
            className="w-4 h-4"
            style={{ accentColor: "var(--color-brand)" }}
            aria-label="Compare with Nifty 50 sector median"
          />
          <span
            className="text-xs font-medium"
            style={{ color: "var(--color-text)" }}
          >
            Compare with Nifty 50 median
          </span>
        </label>
      </div>

      {/* Share modal */}
      {shareOpen && (
        <div
          className="fixed inset-0 z-50 flex items-end md:items-center justify-center"
          role="dialog"
          aria-modal="true"
          aria-labelledby="share-prism-title"
        >
          <button
            type="button"
            aria-label="Close"
            onClick={() => setShareOpen(false)}
            className="absolute inset-0"
            style={{ background: "rgba(0,0,0,0.4)" }}
          />
          <div
            className="relative rounded-t-2xl md:rounded-2xl border border-border p-5 w-full md:max-w-md mx-auto max-h-[90vh] overflow-y-auto"
            style={{ background: "var(--color-surface)" }}
          >
            <div className="flex items-start justify-between">
              <h3
                id="share-prism-title"
                className="text-base font-bold"
                style={{ color: "var(--color-text)" }}
              >
                Share your Portfolio Prism
              </h3>
              <button
                type="button"
                onClick={() => setShareOpen(false)}
                aria-label="Close"
                className="inline-flex items-center justify-center min-w-[44px] min-h-[44px]"
                style={{ color: "var(--color-caption)" }}
              >
                &times;
              </button>
            </div>
            <p
              className="text-xs mt-1"
              style={{ color: "var(--color-caption)" }}
            >
              Model estimate. Not investment advice.
            </p>
            <div className="mt-4 flex justify-center">
              {prismData && (
                <Prism
                  data={prismData}
                  size={size}
                  mode="signature"
                  sectorOverlay={overlayNifty}
                  firstView={false}
                />
              )}
            </div>
            <p
              className="mt-4 text-sm"
              style={{ color: "var(--color-text)" }}
            >
              Screenshot to share.
            </p>
            <button
              type="button"
              onClick={() => setShareOpen(false)}
              className="mt-4 w-full inline-flex items-center justify-center min-h-[44px] text-sm font-semibold px-4 py-2 rounded-lg active:scale-[0.98] transition"
              style={{
                background: "var(--color-brand)",
                color: "var(--color-bg)",
              }}
            >
              Got it
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
