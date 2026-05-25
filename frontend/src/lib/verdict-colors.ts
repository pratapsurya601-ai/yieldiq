/**
 * verdict-colors.ts — verdict-driven color cascade tokens.
 *
 * Manifesto Rule 9 ("Color is signal, not theme"): the page hero literally
 * looks different colors for different verdicts. Undervalued → emerald/teal,
 * Overvalued → amber/orange, Fairly Valued → slate, Under Review / Data
 * Limited → washed-out slate/gray (intentional "we're not sure" tone).
 *
 * Tier resolution priority:
 *   1. explicit `verdict` string === "under_review"            → under_review
 *   2. explicit `verdict` string === "data_limited" OR mos null → data_limited
 *   3. numeric MoS thresholds (>20 / <-10 / else)              → un/over/fair
 *
 * Keep the verdict-string check synced with the backend enum exposed
 * via lib/verdict.ts (RawVerdict). The MoS thresholds mirror the
 * "Undervalued / Fairly Valued / Overvalued" bands the user-facing
 * copy already uses across the analysis page.
 *
 * Tailwind class strings are intentionally listed in full so the JIT
 * compiler can statically extract them. Do NOT build classes dynamically
 * by concatenating shades — Tailwind will not see them.
 *
 * Note: `to-rust-800` is not a default Tailwind color. To avoid
 * extending tailwind.config.js (lower-friction option per spec), we use
 * `to-orange-900` for the overvalued cascade. Reads as a muted rust
 * against the dark image overlay.
 */

export type VerdictTier =
  | "undervalued"
  | "fairly_valued"
  | "overvalued"
  | "under_review"
  | "data_limited"

export function verdictTierFromMos(
  mos_pct: number | null | undefined,
  verdict?: string | null,
): VerdictTier {
  const v = (verdict ?? "").toString().toLowerCase().replace(/\s+/g, "_")
  if (v === "under_review" || v === "unavailable" || v === "avoid") {
    return "under_review"
  }
  if (v === "data_limited" || mos_pct == null || !Number.isFinite(mos_pct)) {
    return "data_limited"
  }
  if (mos_pct > 20) return "undervalued"
  if (mos_pct < -10) return "overvalued"
  return "fairly_valued"
}

export interface VerdictColorTokens {
  /** Tailwind `from-*` gradient class. */
  from: string
  /** Tailwind `to-*` gradient class. */
  to: string
  /** Accent shade token (no `bg-` / `text-` prefix). */
  accent: string
  /** Tailwind `text-*` class for high-contrast text on the gradient. */
  text: string
  /** Solid Tailwind `bg-*` for the 4px sticky verdict bar. */
  bar: string
}

export const VERDICT_COLORS: Record<VerdictTier, VerdictColorTokens> = {
  undervalued: {
    from: "from-emerald-600",
    to: "to-teal-700",
    accent: "emerald-500",
    text: "text-emerald-50",
    bar: "bg-emerald-500",
  },
  fairly_valued: {
    from: "from-slate-500",
    to: "to-slate-700",
    accent: "slate-400",
    text: "text-slate-50",
    bar: "bg-slate-400",
  },
  overvalued: {
    from: "from-amber-700",
    // rust-800 isn't a default Tailwind color — orange-900 reads as a
    // muted rust at this opacity and keeps tailwind.config.js untouched.
    to: "to-orange-900",
    accent: "amber-500",
    text: "text-amber-50",
    bar: "bg-amber-500",
  },
  under_review: {
    from: "from-slate-400",
    to: "to-slate-600",
    accent: "slate-300",
    text: "text-slate-100",
    bar: "bg-slate-400",
  },
  data_limited: {
    from: "from-gray-300",
    to: "to-gray-500",
    accent: "gray-300",
    text: "text-gray-100",
    bar: "bg-gray-400",
  },
}

/** Plain-English label for the verdict pill rendered on the hero. */
export function verdictTierLabel(tier: VerdictTier): string {
  switch (tier) {
    case "undervalued":
      return "Undervalued"
    case "overvalued":
      return "Overvalued"
    case "fairly_valued":
      return "Fairly Valued"
    case "under_review":
      return "Under Review"
    case "data_limited":
      return "Insufficient Data"
  }
}
