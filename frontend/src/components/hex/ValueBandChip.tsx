"use client"

/**
 * ValueBandChip — Stage 1 of 2 (NOT WIRED).
 *
 * This component renders the new sector-percentile-based "value band"
 * label that will replace the current Value axis numeric percentile in
 * the Hex/Prism renderers. The backend `band` field has not shipped
 * yet, so this PR adds the chip in isolation. Stage 2 will swap the
 * existing Value axis renderer for this chip.
 *
 * Do not import outside the dev preview page until Stage 2.
 */

export type ValueBand =
  | "strong_discount"
  | "below_peers"
  | "in_range"
  | "above_peers"
  | "notably_overvalued"
  | "data_limited"

export interface ValueBandChipProps {
  band: ValueBand
  label: string
  percentile?: number | null
  why?: string
  sectorPeers?: number
  sectorLabel?: string
}

// Band -> visual treatment. Tailwind utility classes only; no new
// colors. Tokens from globals.css remain authoritative for app-wide
// theming — these utility classes are scoped to this chip.
const BAND_STYLE: Record<ValueBand, string> = {
  strong_discount:
    "bg-green-600 text-white border border-green-700",
  below_peers:
    "bg-green-300 text-green-950 border border-green-400",
  in_range:
    "bg-gray-200 text-gray-900 border border-gray-300",
  above_peers:
    "bg-amber-500 text-white border border-amber-600",
  notably_overvalued:
    "bg-red-600 text-white border border-red-700",
  data_limited:
    "bg-transparent text-gray-500 border border-dashed border-gray-400",
}

function formatPercentile(p: number | null | undefined): string | null {
  if (p === null || p === undefined || Number.isNaN(p)) return null
  const clamped = Math.max(0, Math.min(100, Math.round(p)))
  return `${clamped}th`
}

export function ValueBandChip({
  band,
  label,
  percentile,
  why,
  sectorPeers,
  sectorLabel,
}: ValueBandChipProps) {
  const isDataLimited = band === "data_limited"
  const text = isDataLimited ? "—" : label
  const pctText = isDataLimited ? null : formatPercentile(percentile)

  // Tooltip content — surfaced as the native title for now. Stage 2
  // may upgrade to a click-to-open popover; keep behavior minimal here.
  const tooltipParts: string[] = []
  if (why) tooltipParts.push(why)
  if (!isDataLimited && sectorPeers && sectorLabel) {
    tooltipParts.push(`Sector: ${sectorLabel} (n=${sectorPeers})`)
  } else if (!isDataLimited && sectorPeers) {
    tooltipParts.push(`Peers: n=${sectorPeers}`)
  }
  const tooltip = tooltipParts.join(" · ") || undefined

  return (
    <span
      role="status"
      aria-label={`Value band: ${text}${pctText ? `, ${pctText} percentile` : ""}`}
      title={tooltip}
      data-band={band}
      data-testid="value-band-chip"
      className={[
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1",
        "text-xs font-medium tabular-nums",
        BAND_STYLE[band],
      ].join(" ")}
    >
      <span data-testid="value-band-chip-label">{text}</span>
      {pctText ? (
        <span
          aria-hidden="true"
          className="opacity-80"
          data-testid="value-band-chip-percentile"
        >
          {pctText}
        </span>
      ) : null}
    </span>
  )
}

export default ValueBandChip
