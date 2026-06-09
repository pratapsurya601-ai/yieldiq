/**
 * Sparkline smoke tests.
 *
 * Locks the post-2026-06-09 home-page polish behavior:
 *   - Renders an SVG polyline with the correct number of points and
 *     non-degenerate stroke coordinates for a strictly-monotonic series.
 *   - Auto-color = green when last >= first (uptrend).
 *   - Auto-color = red when last < first (downtrend).
 *   - Empty / single-value arrays return null so callers don't need to
 *     length-check before rendering.
 *   - Custom color string overrides the auto direction-derived color.
 *
 * No network mock — the component is pure SVG and reads no global state.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import { Sparkline } from "@/components/common/Sparkline"

describe("Sparkline", () => {
  it("renders a polyline with one point per value for a monotonic uptrend [1,2,3,4]", () => {
    render(<Sparkline values={[1, 2, 3, 4]} width={56} height={18} />)
    const svg = screen.getByTestId("sparkline-svg")
    const poly = svg.querySelector("polyline")
    expect(poly).not.toBeNull()
    const pts = (poly?.getAttribute("points") ?? "").trim().split(/\s+/)
    // 4 input values → 4 plotted points.
    expect(pts.length).toBe(4)
    // First point is leftmost (x≈1 after the 1px pad), last is rightmost
    // (x≈55 = width-pad). Y axis is inverted: the smallest value (1) maps
    // to the BOTTOM of the SVG, so its y should be >= the y of value 4.
    const [x0, y0] = pts[0].split(",").map(Number)
    const [x3, y3] = pts[3].split(",").map(Number)
    expect(x0).toBeCloseTo(1, 1)
    expect(x3).toBeCloseTo(55, 1)
    expect(y0).toBeGreaterThan(y3)
  })

  it("uses the green palette color (#22c55e) when last >= first (uptrend)", () => {
    render(<Sparkline values={[10, 12, 14, 18]} />)
    const poly = screen.getByTestId("sparkline-line")
    expect(poly.getAttribute("stroke")).toBe("#22c55e")
    // Fill path inherits the same color at 0.15 opacity.
    const fill = screen.getByTestId("sparkline-fill")
    expect(fill.getAttribute("fill")).toBe("#22c55e")
  })

  it("uses the red palette color (#ef4444) when last < first (downtrend)", () => {
    render(<Sparkline values={[100, 95, 92, 80]} />)
    const poly = screen.getByTestId("sparkline-line")
    expect(poly.getAttribute("stroke")).toBe("#ef4444")
  })

  it("returns null for empty or single-value arrays (no SVG rendered)", () => {
    const { container, rerender } = render(<Sparkline values={[]} />)
    expect(container.querySelector("svg")).toBeNull()
    rerender(<Sparkline values={[42]} />)
    expect(container.querySelector("svg")).toBeNull()
  })

  it("honours a custom CSS color string override (rgb / hex / named)", () => {
    render(<Sparkline values={[1, 2, 3]} color="#8b5cf6" />)
    const poly = screen.getByTestId("sparkline-line")
    // The auto-derived color for an uptrend would be green; the override
    // wins and the polyline stroke matches the custom hex.
    expect(poly.getAttribute("stroke")).toBe("#8b5cf6")
  })
})
