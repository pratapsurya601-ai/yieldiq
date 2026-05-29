"use client"

/**
 * MosAlertChip — contextual "Notify me at X% discount" strip rendered
 * below the Discount-to-FV stat in the EditorialHero (when
 * `compactSummary` is on so it benefits from the space freed by #674
 * collapsing the 8 hero metrics down to 3).
 *
 * Audit #242 / chassis 2026-05-26. Reuses the existing alerts pipeline
 * exactly — no new backend endpoints, no migration, no canary:
 *
 *   POST /api/v1/alerts/create
 *     { ticker, alert_type: "mos_above", target_price: <pct: 0..50> }
 *
 * For the `mos_above` kind the threshold is interpreted as a margin-of-
 * safety percentage (the hourly evaluator fires when the live MoS
 * crosses above it). Delivery uses the existing email + PWA push
 * channels wired in task #78 — no new delivery surface here.
 *
 * SEBI vocabulary note: copy uses "Discount to FV" (the label EditorialHero
 * itself uses post-#674) — NOT "margin of safety" or "buy" — and avoids
 * every banned word in backend/services/analysis/sebi_filter.py.
 */

import { useCallback, useMemo, useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { Bell, BellRing } from "lucide-react"

import { createAlert } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { formatCurrency } from "@/lib/utils"

const DISCOUNT_STEPS = [0, 10, 20, 30, 40, 50] as const
const DEFAULT_STEP = 20

export interface MosAlertChipProps {
  /** Bare or .NS-suffixed ticker. Forwarded to the alerts API as-is
   * (router uppercases + trims server-side). */
  ticker: string
  /** Fair value in company currency. Used to compute the implied
   * trigger price the user is alerting at. Strip omits itself when
   * fairValue is not a finite positive number — the alert payload
   * would still be valid (threshold is a percent) but the price hint
   * would be meaningless. */
  fairValue: number
  /** Currency code from the prism payload (e.g. "INR"). */
  currency: string
  /** Current signed margin-of-safety percent. Optional — used only to
   * pre-select the default step closer to the live discount when the
   * stock is already at a meaningful discount (>= 10%). */
  currentMos?: number | null
}

export default function MosAlertChip({
  ticker,
  fairValue,
  currency,
  currentMos,
}: MosAlertChipProps) {
  const router = useRouter()
  const token = useAuthStore((s) => s.token)

  // Pre-select the smallest step that's still BELOW the current MoS, so
  // the alert default isn't already triggered. Falls back to 20% — the
  // value-investor canon — when MoS is null or already < 10%.
  const initialPct = useMemo<number>(() => {
    if (
      currentMos == null ||
      !Number.isFinite(currentMos) ||
      currentMos < 10
    ) {
      return DEFAULT_STEP
    }
    // Find first step strictly greater than currentMos so the alert
    // would actually need to deepen to fire.
    const next = DISCOUNT_STEPS.find((s) => s > currentMos)
    return next ?? DEFAULT_STEP
  }, [currentMos])

  const [pct, setPct] = useState<number>(initialPct)
  const [confirmed, setConfirmed] = useState<{ pct: number; price: number } | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Implied trigger price = FV × (1 − pct/100). When FV is missing or
  // non-positive, the price hint collapses to null and the chip renders
  // a pct-only label.
  const triggerPrice = useMemo<number | null>(() => {
    if (!Number.isFinite(fairValue) || fairValue <= 0) return null
    return fairValue * (1 - pct / 100)
  }, [fairValue, pct])

  const mutation = useMutation({
    mutationFn: () =>
      createAlert({ ticker, alert_type: "mos_above", target_price: pct }),
    onSuccess: () => {
      setConfirmed({ pct, price: triggerPrice ?? 0 })
      setError(null)
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Could not save alert. Try again."
      setError(detail)
    },
  })

  const onPrimary = useCallback(() => {
    if (!token) {
      router.push(
        "/auth/login?return_to=" +
          encodeURIComponent(
            typeof window !== "undefined" ? window.location.pathname : "/",
          ),
      )
      return
    }
    if (mutation.isPending) return
    mutation.mutate()
  }, [mutation, router, token])

  const onReset = useCallback(() => {
    setConfirmed(null)
    setError(null)
  }, [])

  // ── Confirmation state ───────────────────────────────────────
  if (confirmed) {
    return (
      <div
        data-testid="mos-alert-chip-confirmed"
        role="status"
        aria-live="polite"
        className="mt-3 flex items-center justify-between gap-2 rounded-lg border border-emerald-300 bg-tone-good-bg px-3 py-2 text-[12px] dark:border-emerald-900 dark:bg-emerald-950/30"
      >
        <span className="inline-flex items-center gap-1.5 text-emerald-900 dark:text-emerald-200">
          <BellRing className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            Alerting at{" "}
            {confirmed.price > 0 ? (
              <span className="font-semibold font-mono tabular-nums">
                {formatCurrency(confirmed.price, currency)}
              </span>
            ) : (
              <span className="font-semibold">{confirmed.pct}% discount</span>
            )}
            {confirmed.price > 0 && (
              <>
                {" "}
                &middot;{" "}
                <span className="font-semibold">{confirmed.pct}% discount</span>
              </>
            )}
          </span>
        </span>
        <button
          type="button"
          onClick={onReset}
          className="text-[11px] font-semibold text-tone-good-fg hover:underline dark:text-emerald-300"
        >
          Change
        </button>
      </div>
    )
  }

  // ── Default state ────────────────────────────────────────────
  const primaryLabel = !token
    ? "Sign in to alert"
    : mutation.isPending
    ? "Saving…"
    : "Notify me"

  return (
    <div
      data-testid="mos-alert-chip"
      className="mt-3 rounded-lg border border-border bg-bg px-3 py-2"
    >
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.15em] text-caption">
        <Bell className="h-3 w-3" aria-hidden="true" />
        Notify me when discount reaches
      </div>

      <div
        role="radiogroup"
        aria-label="Discount-to-FV alert threshold"
        className="mt-1.5 flex flex-wrap gap-1"
      >
        {DISCOUNT_STEPS.map((step) => {
          const selected = step === pct
          return (
            <button
              key={step}
              type="button"
              role="radio"
              aria-checked={selected}
              data-testid={`mos-alert-step-${step}`}
              onClick={() => setPct(step)}
              className={
                "px-2 py-0.5 rounded-md text-[11px] font-semibold font-mono tabular-nums border transition " +
                (selected
                  ? "border-brand text-brand bg-brand/5"
                  : "border-border text-caption hover:text-ink hover:border-ink/40")
              }
            >
              {step}%
            </button>
          )
        })}
      </div>

      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="text-[11px] text-body">
          {triggerPrice != null ? (
            <>
              Alert at{" "}
              <span className="font-mono tabular-nums font-semibold text-ink">
                {formatCurrency(triggerPrice, currency)}
              </span>{" "}
              <span className="text-caption">({pct}% discount)</span>
            </>
          ) : (
            <span className="text-caption">{pct}% discount</span>
          )}
        </span>
        <button
          type="button"
          onClick={onPrimary}
          disabled={mutation.isPending}
          data-testid="mos-alert-primary"
          className={
            "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold border transition " +
            "border-brand text-brand bg-brand/5 hover:bg-brand/10 " +
            "disabled:opacity-50 disabled:cursor-not-allowed"
          }
        >
          <Bell className="h-3 w-3" aria-hidden="true" />
          {primaryLabel}
        </button>
      </div>

      {error && (
        <p
          role="alert"
          className="mt-1.5 text-[11px] text-amber-800 dark:text-amber-300"
        >
          {error}
        </p>
      )}
    </div>
  )
}
