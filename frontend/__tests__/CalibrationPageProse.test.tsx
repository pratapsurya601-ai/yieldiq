/**
 * Calibration page — public-copy prose hygiene test (2026-06-11).
 *
 * The /calibration description paragraph was leaking the raw DB
 * table name `fair_value_history` in a code-font / monospace
 * `<code>` element on the public page (prod audit 2026-06-10). This
 * test pins the fix: the description prose MUST be rendered as
 * plain copy ("fair-value history") with NO `<code>` element
 * wrapping the table name. We assert two invariants:
 *
 *   1. The description still mentions the fair-value history (so
 *      the page hasn't been edited to drop the explanatory clause).
 *   2. There is NO `<code>` element in the rendered DOM whose
 *      textContent contains the raw `fair_value_history` token.
 *
 * The page is a Server Component that calls `fetch` at module
 * level via `fetchCalibration`. We stub global.fetch to return a
 * minimal payload so the smoke render succeeds — the prose under
 * test does not depend on the payload contents.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render } from "@testing-library/react"

const CALIBRATION_PAYLOAD = {
  sectors: [
    {
      sector: "Banking",
      ticker_count: 8,
      observation_count: 240,
      median_abs_error_pct: 12.4,
      median_signed_error_pct: -3.1,
      p90_abs_error_pct: 31.2,
      direction_accuracy_pct: 58.5,
      last_observation_date: "2026-06-09",
    },
  ],
  meta: {
    generated_at: "2026-06-10T03:00:00Z",
    lookback_days: 90,
    min_observations: 30,
    quarantine_policy:
      "Pre-manifest-epoch rows and step-unverified rows are excluded.",
    sector_count: 1,
    direction_bands: {
      below_mos_threshold_pct: -10,
      above_mos_threshold_pct: 10,
      forward_return_threshold_pct: 5,
      near_band_return_pct: 2,
    },
  },
}

describe("CalibrationPage — public-copy prose hygiene", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => CALIBRATION_PAYLOAD,
      })) as unknown as typeof fetch,
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it("description prose does NOT wrap the table name in a <code> element", async () => {
    // Dynamic import so the stubbed fetch is in place before the
    // server-component fetcher closes over `global.fetch`.
    const { default: CalibrationPage } = await import(
      "@/app/(marketing)/calibration/page"
    )
    // Server components return a Promise<JSX.Element>; render after
    // awaiting the resolved tree.
    const tree = await CalibrationPage()
    const { container } = render(tree)

    // (1) The descriptive clause must still be present — we did not
    // accidentally delete the sentence, just the code-font styling.
    const text = container.textContent ?? ""
    expect(text).toMatch(/fair-value history/i)

    // (2) No <code> element anywhere in the rendered page may carry
    // the raw `fair_value_history` token. The fix replaces the
    // <code>fair_value_history</code> span with plain prose.
    const codes = Array.from(container.querySelectorAll("code"))
    for (const code of codes) {
      expect(code.textContent ?? "").not.toMatch(/fair_value_history/)
    }
  })
})
