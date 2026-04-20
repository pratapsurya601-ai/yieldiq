"use client"

import { HEX_AXIS_BLURB, HEX_AXIS_ORDER, type HexAxisKey, type HexResponse } from "@/lib/hex"

interface HexLegendProps {
  data: HexResponse
  onAxisTap?: (axis: HexAxisKey) => void
}

const AXIS_LABEL: Record<HexAxisKey, string> = {
  value: "Value",
  quality: "Quality",
  growth: "Growth",
  moat: "Moat",
  safety: "Safety",
  pulse: "Pulse",
}

export default function HexLegend({ data, onAxisTap }: HexLegendProps) {
  return (
    <ul
      className="grid grid-cols-3 gap-2 w-full"
      aria-label="Hex axes"
      style={{ listStyle: "none", padding: 0, margin: 0 }}
    >
      {HEX_AXIS_ORDER.map((key) => {
        const ax = data.axes[key]
        const dataLimited = ax.data_limited
        return (
          <li key={key}>
            <button
              type="button"
              onClick={() => onAxisTap?.(key)}
              title={HEX_AXIS_BLURB[key]}
              className="tap-target w-full flex flex-col items-start rounded-lg px-3 py-2 text-left transition"
              style={{
                background: "var(--color-surface)",
                border: "1px solid var(--color-border)",
                color: "var(--color-body)",
                cursor: onAxisTap ? "pointer" : "default",
              }}
            >
              <span
                className="font-mono uppercase tracking-wide"
                style={{ fontSize: 10, color: "var(--color-caption)" }}
              >
                {AXIS_LABEL[key]}
              </span>
              <span
                className="font-mono tabular-nums font-semibold"
                style={{
                  fontSize: 14,
                  color: dataLimited
                    ? "var(--color-caption)"
                    : "var(--color-ink)",
                  marginTop: 2,
                }}
              >
                {ax.score != null ? ax.score.toFixed(1) : "\u2014"}
                <span
                  style={{
                    fontSize: 10,
                    color: "var(--color-caption)",
                    marginLeft: 2,
                  }}
                >
                  /10
                </span>
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
