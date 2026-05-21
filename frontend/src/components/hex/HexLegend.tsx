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

/**
 * Day-82 (Tier-3 #35, Option E): Hex empty-state informativeness.
 *
 * When a thin-data ticker (PARADEEP-class) lands on the analysis page,
 * the Hex used to collapse to a near-grey hexagon with no explanation.
 * The legend now leads with an explicit coverage line — "Data coverage:
 * 4 of 6 inputs available" — and the limited rows carry an inline
 * "Limited" tag so the dim score reads as intentional, not broken.
 *
 * No layout change to the Hex polygon itself — this is brand-defining
 * art and stays untouched. Polish lives in the legend strip beneath it.
 */
function countAvailableAxes(data: HexResponse): {
  available: number
  total: number
  missing: HexAxisKey[]
} {
  const total = HEX_AXIS_ORDER.length
  const missing = HEX_AXIS_ORDER.filter((k) => data.axes[k]?.data_limited)
  return { available: total - missing.length, total, missing }
}

export default function HexLegend({ data, onAxisTap }: HexLegendProps) {
  const coverage = countAvailableAxes(data)
  const isLimited = coverage.available < coverage.total
  const missingLabels = coverage.missing.map((k) => AXIS_LABEL[k]).join(", ")

  return (
    <div className="w-full flex flex-col gap-2">
      {isLimited && (
        <div
          data-testid="hex-coverage-note"
          className="flex items-start gap-2 rounded-lg px-3 py-2"
          style={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            color: "var(--color-body)",
          }}
        >
          <span
            aria-hidden="true"
            className="inline-flex items-center justify-center rounded-full"
            style={{
              width: 18,
              height: 18,
              flex: "0 0 18px",
              marginTop: 1,
              background: "color-mix(in srgb, var(--color-warning) 18%, transparent)",
              color: "var(--color-warning)",
              fontSize: 11,
              fontWeight: 800,
              fontFamily:
                "var(--font-mono), ui-monospace, SFMono-Regular, monospace",
            }}
          >
            i
          </span>
          <div className="flex flex-col">
            <span
              className="font-mono uppercase tracking-wide"
              style={{ fontSize: 10, color: "var(--color-caption)" }}
            >
              Data coverage
            </span>
            <span
              className="text-sm leading-snug"
              style={{ color: "var(--color-body)" }}
            >
              <span className="font-mono tabular-nums font-bold">
                {coverage.available} of {coverage.total}
              </span>{" "}
              inputs available
              {missingLabels && (
                <>
                  {" · Limited: "}
                  <span className="font-bold">{missingLabels}</span>
                </>
              )}
            </span>
          </div>
        </div>
      )}

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
                aria-label={
                  dataLimited
                    ? `${AXIS_LABEL[key]} — limited data — ${HEX_AXIS_BLURB[key]}`
                    : `${AXIS_LABEL[key]} — ${HEX_AXIS_BLURB[key]}`
                }
                className="tap-target w-full flex flex-col items-start rounded-lg px-3 py-2 text-left transition"
                style={{
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  color: "var(--color-body)",
                  cursor: onAxisTap ? "pointer" : "default",
                }}
              >
                <span className="flex items-center gap-1.5 w-full">
                  <span
                    className="font-mono uppercase tracking-wide"
                    style={{ fontSize: 10, color: "var(--color-caption)" }}
                  >
                    {AXIS_LABEL[key]}
                  </span>
                  {dataLimited && (
                    <span
                      data-testid="hex-axis-limited-tag"
                      className="font-mono uppercase tracking-wide ml-auto rounded px-1"
                      style={{
                        fontSize: 9,
                        fontWeight: 700,
                        color: "var(--color-warning)",
                        background:
                          "color-mix(in srgb, var(--color-warning) 14%, transparent)",
                      }}
                    >
                      Limited
                    </span>
                  )}
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
                  {ax.score != null ? ax.score.toFixed(1) : "—"}
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
    </div>
  )
}
