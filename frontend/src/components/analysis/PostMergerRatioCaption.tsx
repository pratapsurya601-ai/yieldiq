"use client"

/**
 * PostMergerRatioCaption — explainer that renders above the ROE/ROA
 * cards on the Quality tab when the subject ticker has a material
 * M&A event inside its 8-quarter normalisation window.
 *
 * Source field: `AnalysisResponse.ma_event` (see
 * backend/services/ma_event_detector.py). Self-hides when:
 *   - the field is absent (legacy cached payloads, non-M&A tickers),
 *   - `is_within_normalization_window` is false (event predates the
 *     normalisation window — ratios are no longer materially
 *     distorted),
 *   - the structural type is one we don't have explainer copy for
 *     (defensive — the detector pre-filters to a known enum).
 *
 * SEBI-safe: descriptive copy only ("expanded", "reflect", "normalise"),
 * no advisory verbs.
 *
 * ROOT CAUSE #2 + #8 (2026-06-11) — manifest entry
 * `v_ma_event_context_2026_06_11`.
 */

import type { AnalysisResponse } from "@/types/api"

interface Props {
  /** AnalysisResponse.ma_event — `null`/`undefined` self-hides. */
  maEvent: NonNullable<AnalysisResponse["ma_event"]> | null | undefined
  /** Display name for the subject company (falls back to "the company"). */
  companyName?: string | null
  /** Trailing-12-month ROE (percent). Optional — caption skips the line when absent. */
  roePct?: number | null
  /** Trailing-12-month ROA (percent). Optional — caption skips the line when absent. */
  roaPct?: number | null
}

// Human-readable event labels keyed by backend enum. Kept in sync
// with `_EVENT_DESCRIPTIONS` in backend/services/ma_event_detector.py.
const EVENT_LABELS: Record<string, string> = {
  MERGER: "merger",
  REVERSE_MERGER: "reverse merger",
  DEMERGER: "demerger",
  SCHEME_OF_ARRANGEMENT: "scheme of arrangement",
  MATERIAL_ACQUISITION: "material acquisition",
}

// "Reflect this scale jump" for expansion events; "reflect this
// structural change" for splits where the wording would otherwise
// read as a balance-sheet expansion.
const EXPANSION_EVENTS = new Set([
  "MERGER",
  "REVERSE_MERGER",
  "SCHEME_OF_ARRANGEMENT",
  "MATERIAL_ACQUISITION",
])

function fmtMonthYear(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleDateString("en-IN", {
      year: "numeric",
      month: "long",
    })
  } catch {
    return iso
  }
}

function fmtMagnitudePct(v: number | null | undefined): string | null {
  if (v === null || v === undefined || Number.isNaN(v)) return null
  if (v <= 0) return null
  // Round to nearest 5% for the descriptive copy — gives "~70%" or
  // "~40%" feel rather than a false-precision "73.4%". The audit
  // trail still carries the exact `multiplier` for power users.
  const rounded = Math.round(v / 5) * 5
  return `${rounded}%`
}

function fmtRatioPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  return `${v.toFixed(1)}%`
}

function resumeQuarterLabel(
  eventDateIso: string,
  windowQuarters: number,
): string | null {
  try {
    const ev = new Date(eventDateIso)
    if (Number.isNaN(ev.getTime())) return null
    // Move forward windowQuarters * 3 months.
    const target = new Date(ev)
    target.setMonth(target.getMonth() + windowQuarters * 3)
    const m = target.getMonth() + 1 // 1..12
    let q: number
    let fyYear: number
    if (m >= 4 && m <= 6) {
      q = 1
      fyYear = target.getFullYear() + 1
    } else if (m >= 7 && m <= 9) {
      q = 2
      fyYear = target.getFullYear() + 1
    } else if (m >= 10 && m <= 12) {
      q = 3
      fyYear = target.getFullYear() + 1
    } else {
      q = 4
      fyYear = target.getFullYear()
    }
    const yy = String(fyYear % 100).padStart(2, "0")
    return `Q${q} FY${yy}`
  } catch {
    return null
  }
}

export default function PostMergerRatioCaption({
  maEvent,
  companyName,
  roePct,
  roaPct,
}: Props) {
  if (!maEvent) return null
  if (!maEvent.is_within_normalization_window) return null
  const eventLabel = EVENT_LABELS[maEvent.event_type]
  if (!eventLabel) return null

  const subject =
    companyName && companyName.trim().length > 0
      ? companyName.trim()
      : "The company"

  const eventDate = fmtMonthYear(maEvent.event_date)
  const magnitude = fmtMagnitudePct(maEvent.magnitude_pct)
  const expansion = EXPANSION_EVENTS.has(maEvent.event_type)

  const headlineParts: string[] = []
  headlineParts.push(
    `${subject} completed a ${eventLabel} in ${eventDate}`,
  )
  if (magnitude && expansion) {
    headlineParts.push(
      `, expanding the balance sheet by roughly ${magnitude}`,
    )
  } else if (magnitude && !expansion) {
    headlineParts.push(
      `, restructuring roughly ${magnitude} of the balance sheet`,
    )
  }
  headlineParts.push(".")

  const ratioLine = (() => {
    const haveRoe = roePct !== null && roePct !== undefined
    const haveRoa = roaPct !== null && roaPct !== undefined
    if (haveRoe && haveRoa) {
      return ` Trailing 12-month ROE (${fmtRatioPct(roePct)}) and ROA (${fmtRatioPct(roaPct)}) reflect this one-time scale jump rather than a change in underlying franchise.`
    }
    if (haveRoe) {
      return ` Trailing 12-month ROE (${fmtRatioPct(roePct)}) reflects this one-time scale jump rather than a change in underlying franchise.`
    }
    if (haveRoa) {
      return ` Trailing 12-month ROA (${fmtRatioPct(roaPct)}) reflects this one-time scale jump rather than a change in underlying franchise.`
    }
    return ` The trailing return ratios below reflect this one-time scale jump rather than a change in underlying franchise.`
  })()

  const resumeLabel = resumeQuarterLabel(
    maEvent.event_date,
    maEvent.normalization_window_quarters,
  )
  const normalisationLine = resumeLabel
    ? ` Normalised year-on-year readings resume from ${resumeLabel} (${maEvent.normalization_window_quarters} quarters post-event).`
    : ` Normalised year-on-year readings resume ${maEvent.normalization_window_quarters} quarters post-event.`

  const description = maEvent.description?.trim() ?? ""
  const sourceUrl = maEvent.source_url ?? null

  return (
    <section
      data-testid="post-merger-ratio-caption"
      className="rounded-2xl border border-l-4 border-border border-l-brand bg-bg p-4"
      aria-label="Post-merger context for trailing return ratios"
    >
      <div className="flex items-center gap-2 mb-1">
        <span
          aria-hidden
          className="inline-block h-1.5 w-1.5 rounded-full bg-brand"
        />
        <span className="text-[0.68rem] font-semibold uppercase tracking-[0.08em] text-brand">
          Post-merger context
        </span>
      </div>
      <p className="text-sm font-semibold text-ink leading-snug">
        Trailing ratios reflect one-time M&amp;A scale jump
      </p>
      <p className="mt-1 text-sm text-body leading-relaxed">
        {headlineParts.join("")}
        {ratioLine}
        {normalisationLine}
      </p>
      {description && (
        <p className="mt-2 text-[11px] text-caption leading-relaxed">
          {description}
          {sourceUrl ? (
            <>
              {" "}
              <a
                href={sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="underline decoration-dotted underline-offset-2 hover:text-ink"
              >
                Filing
              </a>
              .
            </>
          ) : (
            "."
          )}
        </p>
      )}
    </section>
  )
}
