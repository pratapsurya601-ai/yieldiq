"use client"

import { useEffect } from "react"
import Link from "next/link"
import {
  HEX_AXIS_BLURB,
  type HexAxisKey,
  type HexResponse,
} from "@/lib/hex"

interface HexExplainerProps {
  open: boolean
  axis: HexAxisKey | null
  data: HexResponse
  onClose: () => void
}

const AXIS_LABEL: Record<HexAxisKey, string> = {
  value: "Value",
  quality: "Quality",
  growth: "Growth",
  moat: "Moat",
  safety: "Safety",
  pulse: "Pulse",
}

function labelTone(
  label: string,
): "positive" | "neutral" | "negative" {
  if (label === "Strong" || label === "Positive") return "positive"
  if (label === "Weak" || label === "Negative") return "negative"
  return "neutral"
}

export default function HexExplainer({
  open,
  axis,
  data,
  onClose,
}: HexExplainerProps) {
  // Close on Escape.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open || !axis) return null

  const ax = data.axes[axis]
  const median = data.sector_medians?.[axis] ?? null
  const tone = labelTone(ax.label)
  const toneColor =
    tone === "positive"
      ? "var(--color-success)"
      : tone === "negative"
      ? "var(--color-danger)"
      : "var(--color-caption)"

  const comparison =
    median !== null
      ? ax.score > median + 0.3
        ? "You're above average"
        : ax.score < median - 0.3
        ? "You're below average"
        : "In line with peers"
      : null

  return (
    <div
      className="fixed inset-0 z-50"
      role="dialog"
      aria-modal="true"
      aria-labelledby="hex-explainer-title"
    >
      {/* Backdrop */}
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
      />

      {/* Sheet (bottom on mobile, right drawer on md+) */}
      <div
        className="
          absolute left-0 right-0 bottom-0 max-h-[85vh]
          md:left-auto md:right-0 md:top-0 md:bottom-0 md:max-h-none md:w-[420px]
          overflow-y-auto rounded-t-2xl md:rounded-none
          border md:border-l md:border-t-0
          p-5 md:p-6
        "
        style={{
          background: "var(--color-bg)",
          borderColor: "var(--color-border)",
          color: "var(--color-body)",
        }}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p
              className="font-mono uppercase tracking-wide"
              style={{ fontSize: 11, color: "var(--color-caption)" }}
            >
              {data.ticker} · Model estimate
            </p>
            <h2
              id="hex-explainer-title"
              className="font-display font-bold"
              style={{
                fontSize: 24,
                color: "var(--color-ink)",
                marginTop: 4,
              }}
            >
              {AXIS_LABEL[axis]}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="tap-target inline-flex items-center justify-center rounded-full"
            style={{
              color: "var(--color-caption)",
              background: "var(--color-surface)",
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Score + label */}
        <div className="mt-4 flex items-baseline gap-3">
          <span
            className="font-mono tabular-nums font-bold"
            style={{ fontSize: 40, color: "var(--color-ink)", lineHeight: 1 }}
          >
            {ax.score.toFixed(1)}
          </span>
          <span
            className="font-mono"
            style={{ fontSize: 14, color: "var(--color-caption)" }}
          >
            /10
          </span>
          <span
            className="inline-flex items-center rounded-full px-2.5 py-1"
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: toneColor,
              background: "var(--color-surface)",
              border: `1px solid ${toneColor}33`,
            }}
          >
            {ax.label}
          </span>
        </div>

        {/* Why text */}
        {ax.why && (
          <p
            className="mt-4 text-sm leading-relaxed"
            style={{ color: "var(--color-body)" }}
          >
            {ax.why}
          </p>
        )}

        {/* Educational blurb */}
        <div
          className="mt-4 rounded-lg p-3"
          style={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
          }}
        >
          <p
            className="font-mono uppercase tracking-wide mb-1"
            style={{ fontSize: 10, color: "var(--color-caption)" }}
          >
            What this means
          </p>
          <p
            className="text-sm leading-relaxed"
            style={{ color: "var(--color-body)" }}
          >
            {HEX_AXIS_BLURB[axis]}
          </p>
        </div>

        {/* Median comparison */}
        {median !== null && (
          <p
            className="mt-4 text-sm"
            style={{ color: "var(--color-body)" }}
          >
            <span className="font-mono tabular-nums font-semibold">
              Your stock: {ax.score.toFixed(1)}
            </span>
            <span style={{ color: "var(--color-caption)" }}>
              {" · "}Sector median:{" "}
            </span>
            <span className="font-mono tabular-nums">{median.toFixed(1)}</span>
            {comparison && (
              <>
                <span style={{ color: "var(--color-caption)" }}>{" · "}</span>
                <span style={{ color: toneColor, fontWeight: 600 }}>
                  {comparison}
                </span>
              </>
            )}
          </p>
        )}

        {ax.data_limited && (
          <p
            className="mt-3 text-xs"
            style={{ color: "var(--color-warning)" }}
          >
            Limited data available for this axis — treat the score as indicative.
          </p>
        )}

        <div className="mt-5">
          <Link
            href={`/glossary#${axis}`}
            className="inline-flex items-center gap-1 text-sm font-semibold tap-target"
            style={{ color: "var(--color-brand)" }}
          >
            Learn more
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="5" y1="12" x2="19" y2="12" />
              <polyline points="12 5 19 12 12 19" />
            </svg>
          </Link>
        </div>
      </div>
    </div>
  )
}
