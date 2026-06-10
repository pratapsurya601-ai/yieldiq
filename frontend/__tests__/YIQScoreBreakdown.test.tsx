/**
 * YIQScoreBreakdown tests (feat/analysis-yiq-score-breakdown, 2026-06-10).
 *
 * Pins the Tickertape-style 5-pillar trust composition reveal:
 *   - renders nothing when every pillar is null (no false "0 of 120")
 *   - the headline numerator is the SUM of floored contributions
 *   - bar widths animate from 0 -> target on mount (one rAF tick)
 *   - reduced-motion users get target widths immediately (no transition)
 *   - banks / holdcos (sensitivity null, composite_agreement null) read
 *     as "X of 5 pillars applicable" with N/A rows showing the
 *     methodology-not-applicable caveat instead of the why string
 *   - bars are role="meter" with aria-valuetext for screen readers
 *
 * The numerator is *floored*, not rounded — see component header for
 * rationale (matches docs/diagnostics/phase-c-score-formula-2026-05-25.md).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, act } from "@testing-library/react"

import YIQScoreBreakdown, {
  type YIQConfidencePillars,
} from "@/components/analysis/YIQScoreBreakdown"

// Build pillar fixtures from fragments so the SEBI vocab guard's
// diff-only scan never trips on any banned token that might creep
// into a future pillar name. Pattern B from root CLAUDE.md rule #5.
function pillars(partial: Partial<YIQConfidencePillars>): YIQConfidencePillars {
  return {
    data_quality: null,
    model_confidence: null,
    valuation_stability: null,
    sensitivity: null,
    composite_agreement: null,
    ...partial,
  }
}

// 72/100 * 25 = 18.00 → 18   (data_quality)
// 84/100 * 25 = 21.00 → 21   (model_confidence)
// 73/100 * 25 = 18.25 → 18   (valuation_stability)
// 48/100 * 25 = 12.00 → 12   (sensitivity)
// 46/100 * 20 =  9.20 →  9   (composite_agreement)
// Sum = 78 → matches the brief's headline example (78/120).
const FULL_PILLARS: YIQConfidencePillars = pillars({
  data_quality: 72,
  model_confidence: 84,
  valuation_stability: 73,
  sensitivity: 48,
  composite_agreement: 46,
})

// Banks shape: sensitivity + composite_agreement are null.
const BANK_PILLARS: YIQConfidencePillars = pillars({
  data_quality: 80,
  model_confidence: 70,
  valuation_stability: 60,
})

beforeEach(() => {
  // jsdom defaults matchMedia → undefined; default to "no preference"
  // unless a test overrides for the reduced-motion path.
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("YIQScoreBreakdown", () => {
  it("renders nothing when every pillar is null", () => {
    const { container } = render(
      <YIQScoreBreakdown ticker="TCS" pillars={pillars({})} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("renders headline numerator as the floored contribution sum", () => {
    render(<YIQScoreBreakdown ticker="TCS" pillars={FULL_PILLARS} />)
    const num = screen.getByTestId("yiq-score-breakdown-numerator")
    expect(num.textContent).toBe("78")
  })

  it("denominator is fixed at 120 (sum of weights)", () => {
    render(<YIQScoreBreakdown ticker="TCS" pillars={FULL_PILLARS} />)
    expect(screen.getByText(/\/ 120/)).toBeInTheDocument()
  })

  it("renders all 5 pillar rows with weighted contributions", () => {
    render(<YIQScoreBreakdown ticker="TCS" pillars={FULL_PILLARS} />)
    // Each pillar's value cell carries a stable testid.
    expect(
      screen.getByTestId("yiq-pillar-data_quality-value").textContent,
    ).toMatch(/\+18\s*\/\s*25/)
    expect(
      screen.getByTestId("yiq-pillar-model_confidence-value").textContent,
    ).toMatch(/\+21\s*\/\s*25/)
    expect(
      screen.getByTestId("yiq-pillar-valuation_stability-value").textContent,
    ).toMatch(/\+18\s*\/\s*25/)
    expect(
      screen.getByTestId("yiq-pillar-sensitivity-value").textContent,
    ).toMatch(/\+12\s*\/\s*25/)
    expect(
      screen.getByTestId("yiq-pillar-composite_agreement-value").textContent,
    ).toMatch(/\+9\s*\/\s*20/)
  })

  it("shows the applicable-pillar count in the subheading", () => {
    render(<YIQScoreBreakdown ticker="TCS" pillars={FULL_PILLARS} />)
    expect(screen.getByText(/5 of 5 pillars applicable/)).toBeInTheDocument()
  })

  it("hides non-applicable pillars from the count and shows N/A caveat", () => {
    render(<YIQScoreBreakdown ticker="HDFCBANK" pillars={BANK_PILLARS} />)
    expect(screen.getByText(/3 of 5 pillars applicable/)).toBeInTheDocument()
    // N/A rows render an em-dash in the value cell
    expect(
      screen.getByTestId("yiq-pillar-sensitivity-value").textContent,
    ).toMatch(/—\s*\/\s*25/)
    expect(
      screen.getByTestId("yiq-pillar-composite_agreement-value").textContent,
    ).toMatch(/—\s*\/\s*20/)
    // and the methodology-not-applicable caveat text
    expect(
      screen.getByText(/sensitivity not applicable/i),
    ).toBeInTheDocument()
    // "Single-estimator path" shows up in both the composite_agreement
    // pillar caveat AND the footer disclaimer — assert at least one
    // match exists (don't pin on a single occurrence).
    expect(
      screen.getAllByText(/Single-estimator path/i).length,
    ).toBeGreaterThanOrEqual(1)
  })

  it("uses role=meter with aria-valuetext on every bar track", () => {
    render(<YIQScoreBreakdown ticker="TCS" pillars={FULL_PILLARS} />)
    const meters = screen.getAllByRole("meter")
    expect(meters).toHaveLength(5)
    // First row is Data Quality → +18 / 25
    expect(meters[0].getAttribute("aria-valuenow")).toBe("18")
    expect(meters[0].getAttribute("aria-valuemax")).toBe("25")
    expect(meters[0].getAttribute("aria-valuetext")).toBe("18 of 25")
  })

  it("animates bars from 0 width to target on mount (one rAF tick)", () => {
    // Capture the rAF callback so we can run it manually.
    const rafSpy = vi
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((cb: FrameRequestCallback) => {
        // Don't fire automatically — the test drives this.
        void cb
        return 1 as unknown as number
      })

    const { container } = render(
      <YIQScoreBreakdown ticker="TCS" pillars={FULL_PILLARS} />,
    )
    const firstBar = container.querySelector<HTMLElement>(
      '[data-testid="yiq-pillar-data_quality-bar"]',
    )
    expect(firstBar).not.toBeNull()
    // Pre-mount tick: bar width is 0%.
    expect(firstBar!.style.width).toBe("0%")

    // Drive the captured rAF callback → triggers the mounted-true setState.
    act(() => {
      const cb = rafSpy.mock.calls[0]?.[0]
      cb?.(performance.now())
    })

    // Post-mount: width is 72/25 of 25 → 72% (data quality = 72 → 18/25).
    expect(firstBar!.style.width).toBe("72%")
    // Transition is non-empty (animated path).
    expect(firstBar!.style.transition).not.toBe("none")
  })

  it("skips the animation when prefers-reduced-motion is set", () => {
    ;(window.matchMedia as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (query: string) => ({
        matches: query.includes("reduce"),
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }),
    )

    const { container } = render(
      <YIQScoreBreakdown ticker="TCS" pillars={FULL_PILLARS} />,
    )
    const bar = container.querySelector<HTMLElement>(
      '[data-testid="yiq-pillar-data_quality-bar"]',
    )
    expect(bar).not.toBeNull()
    // Width is at target immediately (no rAF wait), transition disabled.
    expect(bar!.style.width).toBe("72%")
    expect(bar!.style.transition).toBe("none")
  })
})
