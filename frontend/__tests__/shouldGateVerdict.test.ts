/**
 * Day-94 (2026-05-22) — Audit #5 P1: asymmetric bear-side bypass on
 * shouldGateVerdict.
 *
 * Audit #5 flagged 4-of-17 audit-universe tickers rendering
 * "fairly_valued" pills despite material negative MoS:
 *   - SUNPHARMA  MoS -33%
 *   - MARUTI     MoS -31%
 *   - SBIN       MoS -31%
 *   - ASIANPAINT MoS -47%
 *
 * Root cause: Day-91's gate is symmetric — it fires whenever
 * confidence < 60 OR scenario band > 25% of price, regardless of MoS
 * direction. Bull side stays gated on purpose ("buying on a noisy
 * deep-value signal" is the larger trust risk); bear side must
 * surface the overvalued read honestly.
 *
 * These tests pin: bear-side bypass fires at MoS <= -25 with
 * confidence >= 40, bull-side gate is PRESERVED (TCS-class wide-band
 * +48% MoS at 67% confidence still gates), data_limited still
 * short-circuits, low confidence (<40) still gates even on the bear
 * side.
 */

import { describe, it, expect } from "vitest"

import {
  BEAR_OVERVALUED_BYPASS_CONFIDENCE,
  BEAR_OVERVALUED_BYPASS_MOS,
  BULL_UNDERVALUED_BYPASS_CONFIDENCE,
  BULL_UNDERVALUED_BYPASS_MOS,
  LOW_CONFIDENCE_THRESHOLD,
  WIDE_BAND_RATIO_THRESHOLD,
  shouldGateVerdict,
} from "@/lib/utils"

describe("shouldGateVerdict — Day-94 bear-side bypass", () => {
  it("exports the bear-side bypass thresholds as named constants", () => {
    expect(BEAR_OVERVALUED_BYPASS_MOS).toBe(-25)
    expect(BEAR_OVERVALUED_BYPASS_CONFIDENCE).toBe(40)
    // Sanity: bull side untouched. Threshold bumped 60 → 70 on
    // 2026-06-07 (analysis-page-ui-audit-phase0 cluster G) to catch
    // TCS-class confidence-67 reads that contradicted the
    // AdrCohortBanner's "data limited" warning.
    expect(LOW_CONFIDENCE_THRESHOLD).toBe(70)
    expect(WIDE_BAND_RATIO_THRESHOLD).toBe(0.25)
  })

  // ── Audit #5 affected tickers ──────────────────────────────
  it("does NOT gate SUNPHARMA-class (MoS -33, confidence 55)", () => {
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 55,
        marginOfSafety: -33,
        currentPrice: 100,
        bullCase: 120,
        bearCase: 80,
      }),
    ).toBe(false)
  })

  it("does NOT gate ASIANPAINT-class (MoS -47, confidence 55, wide band)", () => {
    // Wide band would normally gate (ratio > 0.25), but bear-side
    // bypass must take priority — overpaying with a wide model band
    // is exactly the case where we MUST tell the user "overvalued".
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 55,
        marginOfSafety: -47,
        currentPrice: 100,
        bullCase: 160,
        bearCase: 60, // band = 100 → ratio 1.0, far above 0.25
      }),
    ).toBe(false)
  })

  it("does NOT gate at the exact bypass boundary (MoS -25, confidence 40)", () => {
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 40,
        marginOfSafety: -25,
      }),
    ).toBe(false)
  })

  // ── Bull side PRESERVED ────────────────────────────────────
  it("STILL gates TCS-class (MoS +48, confidence 67, wide band)", () => {
    // Bull side conservative: a high positive MoS at moderate
    // confidence might be wrong upward — buying on a noisy "deep
    // value" signal is the larger trust risk.
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 67,
        marginOfSafety: 48,
        currentPrice: 100,
        bullCase: 180,
        bearCase: 50, // band 130 → ratio 1.3
      }),
    ).toBe(true)
  })

  it("STILL gates a high-confidence bull at wide band (MoS +30, confidence 70)", () => {
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 70,
        marginOfSafety: 30,
        currentPrice: 100,
        bullCase: 150,
        bearCase: 80, // band 70 → ratio 0.7
      }),
    ).toBe(true)
  })

  // ── Floor protections ──────────────────────────────────────
  it("STILL gates low-confidence overvalued (MoS -30, confidence 25)", () => {
    // Low-confidence wins — we will not flip to a confident
    // "overvalued" verdict on a data-thin read.
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 25,
        marginOfSafety: -30,
      }),
    ).toBe(true)
  })

  it("STILL gates data_limited regardless of MoS / confidence", () => {
    expect(
      shouldGateVerdict({
        dataLimited: true,
        confidence: 80,
        marginOfSafety: -50,
      }),
    ).toBe(true)
  })

  it("does NOT bypass when confidence is null (bypass requires explicit confidence read)", () => {
    // The bypass clause requires confidence >= 40 as a positive
    // signal. With confidence null AND no scenario inputs, the Day-91
    // gate also returns false (confidence/band gates both no-op on
    // missing data), so this case stays at its pre-Day-94 behavior:
    // ungated. The pin here is that the bypass clause itself does
    // not fire — i.e. it does not flip a true gate to false.
    const before = shouldGateVerdict({
      dataLimited: false,
      confidence: null,
      currentPrice: 100,
      bullCase: 200, // band 200 → ratio 2.0, fires wide-band gate
      bearCase: 0,
    })
    expect(before).toBe(true)
    // Same inputs + deep negative MoS but null confidence → STILL
    // gated. The bypass must not fire without a confidence read.
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: null,
        marginOfSafety: -40,
        currentPrice: 100,
        bullCase: 200,
        bearCase: 0,
      }),
    ).toBe(true)
  })

  it("STILL gates when MoS is just inside the bypass threshold (MoS -24, confidence 50)", () => {
    // -24 is NOT below -25 → no bypass, falls through to standard
    // confidence < 60 gate.
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 50,
        marginOfSafety: -24,
      }),
    ).toBe(true)
  })

  // ── Back-compat: callers that omit marginOfSafety ─────────
  it("retains pre-Day-94 behavior when marginOfSafety is omitted", () => {
    // Without MoS, no bypass — symmetric Day-91 gate semantics.
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 55,
      }),
    ).toBe(true)
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 80,
      }),
    ).toBe(false)
  })
})

describe("shouldGateVerdict — 2026-06-09 bull-side bypass", () => {
  it("exports the bull-side bypass thresholds as named constants", () => {
    expect(BULL_UNDERVALUED_BYPASS_MOS).toBe(25)
    // Bull-side threshold piggybacks on LOW_CONFIDENCE_THRESHOLD — a
    // bull bypass requires AT LEAST the confidence ceiling the
    // standard low-confidence gate enforces.
    expect(BULL_UNDERVALUED_BYPASS_CONFIDENCE).toBe(LOW_CONFIDENCE_THRESHOLD)
  })

  // ── HDFCBANK on 2026-06-09 (Chrome MCP audit reference) ─────
  it("does NOT gate HDFCBANK-class (MoS +52.9, confidence 90, bear above price)", () => {
    // Bear=941 / bull=1505 / price=738.65 — band/price = 0.76, which
    // would normally fire the wide-band gate. The bull-side bypass
    // must take priority because the bear case ALREADY trades above
    // the current price (no noisy-signal risk to gate against).
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 90,
        marginOfSafety: 52.9,
        currentPrice: 738.65,
        bullCase: 1505.71,
        bearCase: 941.07,
      }),
    ).toBe(false)
  })

  it("does NOT gate at the exact bypass boundary (MoS +25, confidence 70, bear == price)", () => {
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 70,
        marginOfSafety: 25,
        currentPrice: 100,
        bullCase: 150,
        bearCase: 100, // bear exactly at price
      }),
    ).toBe(false)
  })

  // ── Bull-side guards: bypass is INTENTIONALLY stricter than bear-side ──
  it("STILL gates TCS-class (MoS +48, confidence 67) — confidence below threshold", () => {
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 67, // below LOW_CONFIDENCE_THRESHOLD (70)
        marginOfSafety: 48,
        currentPrice: 100,
        bullCase: 180,
        bearCase: 110, // bear above price
      }),
    ).toBe(true)
  })

  it("STILL gates when bear case sits BELOW current price (noisy-signal guard)", () => {
    // Same MoS / confidence as HDFCBANK but with bear < price → the
    // bypass refuses to fire because the bear scenario flips the sign.
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 90,
        marginOfSafety: 30,
        currentPrice: 100,
        bullCase: 200,
        bearCase: 90, // bear UNDER price → noisy-signal risk
      }),
    ).toBe(true)
  })

  it("STILL gates a bull-side read with insufficient MoS (MoS +20, confidence 80, bear above price)", () => {
    // +20 MoS sits below the BULL_UNDERVALUED_BYPASS_MOS floor (25).
    // Standard wide-band gate kicks in.
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 80,
        marginOfSafety: 20,
        currentPrice: 100,
        bullCase: 160,
        bearCase: 105,
      }),
    ).toBe(true)
  })

  it("does NOT bypass when bearCase is missing AND wide-band gate would fire", () => {
    // The bull-side bypass requires bearCase to be a finite number.
    // Without bearCase the bypass clause cannot evaluate the
    // "bear above price" condition, so the function falls through to
    // the standard gates. Here we need to manufacture a case where
    // the standard gates WOULD have fired (confidence < threshold)
    // to confirm the bypass doesn't pull a true gate to false.
    expect(
      shouldGateVerdict({
        dataLimited: false,
        confidence: 65, // below LOW_CONFIDENCE_THRESHOLD (70)
        marginOfSafety: 50,
        currentPrice: 100,
        bullCase: 200,
        // bearCase intentionally omitted → bypass cannot fire
      }),
    ).toBe(true)
  })
})
