/**
 * ScoreBreakdownPanel — "Why this score?" transparency panel.
 *
 * Phase C.3 (2026-05-25). Renders the additive `quality.score_breakdown`
 * object built by backend/services/analysis/service.py post-score-cap.
 * No new typography or color tokens — reuses font-mono, text-caption,
 * text-bg, border tokens already present elsewhere in the analysis page.
 *
 * Uses a native <details>/<summary> for collapsibility so the panel
 * stays as a server component (no client-side state hook required) and
 * still works without JS.
 *
 * Renders nothing when score_breakdown is absent (legacy cached payload
 * or compute failure path — see service.py _score_breakdown try/except).
 */

import type { ScoreBreakdown } from "@/types/api"

interface ScoreBreakdownPanelProps {
  breakdown?: ScoreBreakdown | null
}

export default function ScoreBreakdownPanel({
  breakdown,
}: ScoreBreakdownPanelProps) {
  if (!breakdown || !breakdown.components?.length) return null

  const { components, modifiers, base_score, final_score, note } = breakdown
  const hasModifier = (modifiers?.length ?? 0) > 0

  return (
    <details
      className="rounded-2xl border border-line bg-bg p-4 text-ink"
      aria-label="Score breakdown"
    >
      <summary
        className="flex cursor-pointer items-center justify-between
                   text-[11px] font-semibold uppercase tracking-[0.18em]
                   text-caption hover:text-ink"
      >
        <span>Why this score?</span>
        <span className="font-mono text-xs tabular-nums">
          {final_score}/100
        </span>
      </summary>

      <div className="mt-3 flex flex-col gap-3">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wider text-caption">
              <th className="font-semibold pb-1">Component</th>
              <th className="font-semibold pb-1 text-right">Points</th>
              <th className="font-semibold pb-1 text-right">Max</th>
            </tr>
          </thead>
          <tbody>
            {components.map((c) => (
              <tr key={c.name} className="border-t border-line/40">
                <td className="py-1.5 pr-2">
                  <div className="font-medium">{c.name}</div>
                  <div className="text-[10px] text-caption font-mono">
                    {c.source}
                  </div>
                </td>
                <td className="py-1.5 text-right font-mono tabular-nums">
                  {c.points}
                </td>
                <td className="py-1.5 text-right font-mono tabular-nums text-caption">
                  {c.weight_max}
                </td>
              </tr>
            ))}
            <tr className="border-t border-line">
              <td className="py-1.5 font-semibold uppercase text-[10px] tracking-wider text-caption">
                Base
              </td>
              <td className="py-1.5 text-right font-mono tabular-nums font-semibold">
                {base_score}
              </td>
              <td className="py-1.5 text-right font-mono tabular-nums text-caption">
                100
              </td>
            </tr>
          </tbody>
        </table>

        {hasModifier && (
          <div className="flex flex-col gap-1.5">
            <div className="text-[10px] uppercase tracking-wider text-caption font-semibold">
              Modifiers
            </div>
            {modifiers.map((m, i) => (
              <div
                key={`${m.name}-${i}`}
                className="flex items-start justify-between gap-3 text-xs"
              >
                <div>
                  <div className="font-medium">{m.name}</div>
                  <div className="text-[10px] text-caption">{m.reason}</div>
                </div>
                <div
                  className={
                    "font-mono tabular-nums shrink-0 " +
                    (m.delta < 0 ? "text-red-600" : "text-emerald-600")
                  }
                >
                  {m.delta > 0 ? "+" : ""}
                  {m.delta}
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="flex items-center justify-between border-t border-line pt-2 text-xs">
          <span className="font-semibold uppercase tracking-wider text-[10px] text-caption">
            Final
          </span>
          <span className="font-mono tabular-nums text-sm font-bold">
            {final_score}/100
          </span>
        </div>

        {note && (
          <p className="text-[10px] text-caption leading-snug">{note}</p>
        )}
      </div>
    </details>
  )
}
