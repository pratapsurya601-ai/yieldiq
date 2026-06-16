"use client"

// v2 · Decision Box (fast lane) — verdict pill, MoS hero count-up,
// sequenced fair-value bar, alert slider (visual placeholder), and the
// Spectrum with a pillar-inspector slot fed by Spectrum taps.
//
// PORTED from app/demo/analysis-redesign/DecisionBox.tsx. Mock
// FAIR_VALUE / MOS_PCT / SPECTRUM_* imports are replaced by REAL signals
// resolved through useHeroSignals + the raw valuation ladder.
//
// VERDICT_LAYER_ON gate: the verdict pill, the MoS hero number, the FV
// number, and the Spectrum "value region" verdict text are all gated.
// When the layer is OFF (or the signal is verdict-gated upstream), the
// box falls back to the SEBI-neutral "Under Review" state — numbers are
// suppressed entirely, never rendered hidden-but-computed in the DOM.
import { useState } from "react"
import { TrendingUp, AlertCircle } from "lucide-react"

import type { AnalysisResponse } from "@/types/api"
import type { HeroSignals } from "@/lib/useHeroSignals"
import { formatCurrency } from "@/lib/utils"
import {
  verdictTierFromMos,
  verdictTierLabel,
  type VerdictTier,
} from "@/lib/verdict-colors"

import { seg, useStageClock } from "@/app/demo/analysis-redesign/hooks"
import { DEMO_COLORS } from "@/app/demo/analysis-redesign/theme"
import { Muted, Subh } from "@/app/demo/analysis-redesign/ui"
import SpectrumV2, { type SpectrumAxisReal } from "./SpectrumV2"

/** Tone for the verdict pill chrome derived from the resolved tier. */
function pillToneClass(tier: VerdictTier): string {
  switch (tier) {
    case "undervalued":
      return "bg-tone-good-bg text-tone-good-fg"
    case "overvalued":
      return "bg-tone-warn-bg text-tone-warn-fg"
    default:
      // fairly_valued / under_review / data_limited — neutral info tone.
      return "bg-tone-info-bg text-tone-info-fg"
  }
}

export default function DecisionBoxV2({
  data,
  signals,
  axes,
  overall,
  verdictLayerOn,
}: {
  data: AnalysisResponse
  signals: HeroSignals
  /** Six real spectrum axes (0-10), built by the caller from signals. */
  axes: SpectrumAxisReal[]
  /** Overall 0-10 spectrum score (yieldiq_score / 10). */
  overall: number | null
  /** VERDICT_LAYER_ON — false suppresses verdict pill / MoS / FV / region. */
  verdictLayerOn: boolean
}) {
  const { ref, elapsed, reduced } = useStageClock(2600, 0.12)
  const [alertPct, setAlertPct] = useState(20)
  const [picked, setPicked] = useState<number | null>(null)

  const valuation = data.valuation
  const price = valuation.current_price
  const headlineFv = signals.headlineFairValue
  const discount = signals.discount // signed upside % (MoS-as-upside)

  // The verdict layer is "on" only when the flag is set AND the upstream
  // resolver did not gate the verdict (low confidence / wide band / data
  // limited). Otherwise we collapse to the SEBI-neutral Under-Review
  // state and suppress every verdict-derived number.
  const showVerdict = verdictLayerOn && !signals.verdictGated && !signals.dataLimited

  // Resolve the verdict tier + label from the canonical helper (the same
  // SEBI-vetted vocabulary the live hero uses). When suppressed, force
  // the neutral Under-Review tier.
  const tier: VerdictTier = showVerdict
    ? verdictTierFromMos(discount, signals.verdict)
    : "under_review"
  const verdictLabel = verdictTierLabel(tier)

  // MoS count-up — only when verdict shown AND discount is a real number.
  const showMos = showVerdict && discount != null && Number.isFinite(discount)
  const mosTarget = showMos ? Math.round(discount as number) : 0
  const mosNum = reduced ? mosTarget : Math.round(mosTarget * seg(elapsed, 0, 1200))
  // "below" when positive upside (price under FV), "above" when negative.
  const mosBelow = (discount ?? 0) >= 0

  // ── Sequenced fair-value bar geometry ───────────────────────────────
  // Price fill spans the smaller of {price, FV}; the MoS zone is the gap
  // up to the larger. Marker sits at the price position. Only meaningful
  // when verdict shown + both numbers real + positive.
  const showBar = showVerdict && headlineFv != null && headlineFv > 0 && price > 0
  const barMax = showBar ? Math.max(price, headlineFv as number) : 1
  const pricePct = showBar ? Math.min(100, (price / barMax) * 100) : 0
  const fvPct = showBar ? Math.min(100, ((headlineFv as number) / barMax) * 100) : 0
  // The "fill" is up to the lower value; the zone is the band between.
  const fillPct = Math.min(pricePct, fvPct)
  const zoneLeft = fillPct
  const zoneWidth = Math.abs(pricePct - fvPct)
  const blueW = fillPct * seg(elapsed, 0, 1050)
  const greenScale = seg(elapsed, 1050, 550)
  const markOn = elapsed >= 1600

  // ── Valuation ladder (bear / base / bull) — always honest, raw fields ─
  const { bear_case, base_case, bull_case } = valuation
  const ladder = [
    { label: "Bear", v: bear_case },
    { label: "Base", v: base_case },
    { label: "Bull", v: bull_case },
  ].filter((r) => r.v != null && Number.isFinite(r.v) && r.v > 0)

  // The mockup auto-selects the VALUE band (index 5) once the unfold
  // lands — derived in render so a user tap always wins.
  const selected = picked !== null ? picked : elapsed >= 2500 ? axes.length - 1 : null
  const axis = selected !== null ? axes[selected] ?? null : null

  const alertTargetPrice =
    headlineFv != null && headlineFv > 0 ? headlineFv * (1 - alertPct / 100) : null

  return (
    <section
      ref={ref}
      id="sec-answer"
      className="mb-3.5 scroll-mt-24 rounded-2xl border-2 border-tone-info-bd bg-surface px-4 py-4 md:px-5"
    >
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
        {/* Left — the ten-second answer */}
        <div>
          <div
            className={`mb-2.5 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] ${pillToneClass(tier)}`}
          >
            {tier === "undervalued" ? (
              <TrendingUp size={15} aria-hidden="true" />
            ) : (
              <AlertCircle size={15} aria-hidden="true" />
            )}
            {verdictLabel}
          </div>

          {showMos ? (
            <div className="flex items-baseline gap-2">
              <span
                className={`num text-[40px] font-medium leading-none ${
                  mosBelow ? "text-success" : "text-warning"
                }`}
              >
                {Math.abs(mosNum)}%
              </span>
              <Muted>{mosBelow ? "below fair value" : "above fair value"}</Muted>
            </div>
          ) : (
            <div className="flex items-baseline gap-2">
              <span className="num text-[40px] font-medium leading-none text-caption">—</span>
              <Muted>
                {signals.dataLimited
                  ? "fair value pending more data"
                  : "estimate under review"}
              </Muted>
            </div>
          )}

          {/* Sequenced fair-value bar */}
          {showBar ? (
            <>
              <div className="relative mb-1.5 mt-4 h-[30px] overflow-hidden rounded-lg bg-raised">
                <div
                  className="absolute bottom-0 left-0 top-0 bg-tone-info-bg"
                  style={{ width: `${blueW}%` }}
                />
                <div
                  className="absolute bottom-0 top-0 origin-left bg-tone-good-bg"
                  style={{
                    left: `${zoneLeft}%`,
                    width: `${zoneWidth}%`,
                    transform: `scaleX(${greenScale})`,
                  }}
                />
                <div
                  className="absolute bottom-0 top-0 w-0.5 bg-ink transition-opacity duration-300"
                  style={{ left: `${pricePct}%`, opacity: markOn ? 1 : 0 }}
                />
              </div>
              <div className="flex justify-between text-[12px] text-caption">
                <span className="num">
                  <span className="font-medium text-ink">
                    {formatCurrency(price, data.company.currency, data.company.ticker)}
                  </span>{" "}
                  price
                </span>
                <span className="num">
                  <span className="font-medium text-success">
                    {formatCurrency(headlineFv as number, data.company.currency, data.company.ticker)}
                  </span>{" "}
                  fair value
                </span>
              </div>
            </>
          ) : (
            <div className="mt-4 flex justify-between text-[12px] text-caption">
              <span className="num">
                <span className="font-medium text-ink">
                  {price > 0
                    ? formatCurrency(price, data.company.currency, data.company.ticker)
                    : "—"}
                </span>{" "}
                price
              </span>
              <span className="num text-caption">fair value under review</span>
            </div>
          )}

          {/* Valuation ladder (bear / base / bull) — raw, always shown */}
          {ladder.length > 0 && (
            <div className="mt-3.5 grid grid-cols-3 gap-1.5">
              {ladder.map((r) => (
                <div
                  key={r.label}
                  className="rounded-lg border border-border/60 bg-raised px-2.5 py-1.5 text-center"
                >
                  <div className="text-[10.5px] text-caption">{r.label}</div>
                  <div className="num text-[13.5px] font-medium text-ink">
                    {formatCurrency(r.v as number, data.company.currency, data.company.ticker)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Alert slider — VISUAL PLACEHOLDER. Wiring to the alert-create
              endpoint comes with the dedicated section build; labelled
              honestly so the user knows it is a preview control. */}
          <div className="mt-3.5 flex items-center gap-2.5">
            <label htmlFor="v2-alert" className="whitespace-nowrap text-[12.5px] text-caption">
              Alert at
            </label>
            <input
              id="v2-alert"
              type="range"
              min={10}
              max={35}
              step={1}
              value={alertPct}
              onChange={(e) => setAlertPct(Number(e.target.value))}
              className="flex-1 accent-[var(--color-brand)]"
            />
            <span className="num min-w-[34px] text-[12.5px] font-medium text-ink">{alertPct}%</span>
          </div>
          <Muted className="num mt-1 text-[12px]">
            {alertTargetPrice != null
              ? `Notify me when price falls to ${formatCurrency(alertTargetPrice, data.company.currency, data.company.ticker)}.`
              : "Set up price alerts once the estimate is available."}{" "}
            <span className="not-italic text-caption/70">(preview — alerts wire up next build)</span>
          </Muted>

          {/* Pillar inspector slot (fed by Spectrum taps) */}
          <div
            className="mt-3.5 min-h-[72px] rounded-lg border-l-[3px] bg-raised px-3.5 py-2.5 transition-colors duration-200"
            style={{ borderLeftColor: axis ? axis.c : "transparent" }}
            aria-live="polite"
          >
            {axis ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] font-medium tracking-wide text-ink">{axis.k}</span>
                <span className="num text-[16px] font-medium" style={{ color: axis.d }}>
                  {Math.max(0, Math.min(10, axis.s)).toFixed(1)}
                </span>
                <span className="text-[12px] text-caption">/ 10</span>
              </div>
            ) : (
              <Muted className="text-[11.5px]">Tap a Spectrum band to inspect that pillar.</Muted>
            )}
          </div>
        </div>

        {/* Right — the Spectrum */}
        <div className="text-center">
          <div className="mb-0.5 flex items-center justify-between gap-2">
            <Subh className="m-0">YieldIQ Spectrum</Subh>
            {/* Peer overlay toggle is intentionally absent — no per-axis
                peer feed yet (the one known gap). */}
          </div>
          <SpectrumV2
            axes={axes}
            elapsed={elapsed}
            selected={selected}
            onSelect={setPicked}
            overall={overall}
            regionLabel={showVerdict ? regionLabelFor(tier) : null}
          />
        </div>
      </div>
    </section>
  )
}

/** SEBI-neutral region label for the Spectrum core, assembled from the
 *  canonical verdict tier (descriptive, not advisory). */
function regionLabelFor(tier: VerdictTier): string | null {
  switch (tier) {
    case "undervalued":
      return "VALUE REGION"
    case "overvalued":
      return "PREMIUM REGION"
    case "fairly_valued":
      return "FAIR REGION"
    default:
      return null
  }
}
