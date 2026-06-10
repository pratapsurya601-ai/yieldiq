/**
 * RatioTrendModal — mobile slide-up regression.
 *
 * Pins the fix shipped for tmp/mobile_audit_2026_06_10.md issue #2:
 *   - On mobile viewports (< md), the modal must pin to the bottom of
 *     the screen with a rounded top edge (bottom-sheet pattern), NOT
 *     float in the centre.
 *   - On tablet+ (md+), the centred-card classes must still be
 *     present so the responsive Tailwind variants work.
 *
 * jsdom doesn't run CSS media queries, so we assert on the class
 * names directly — that's enough to catch a regression where someone
 * removes the `md:` prefixed centring or the mobile bottom-pinned
 * classes.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import RatioTrendModal from "@/components/analysis/RatioTrendModal"

const SERIES = [
  { period_end: "2021-03-31", value: 12.4 },
  { period_end: "2022-03-31", value: 14.1 },
  { period_end: "2023-03-31", value: 15.8 },
  { period_end: "2024-03-31", value: 17.2 },
]

function getDialogPanel(): HTMLElement {
  // The dialog wrapper has role="dialog"; the panel is its first
  // child element (the one with the className we care about).
  const dialog = screen.getByRole("dialog")
  const panel = dialog.firstElementChild as HTMLElement | null
  expect(panel).not.toBeNull()
  return panel as HTMLElement
}

describe("RatioTrendModal — mobile slide-up", () => {
  it("renders the panel with bottom-sheet classes on mobile (default)", () => {
    // Simulate a mobile viewport so any future client-side branches
    // pick the mobile path. Today the responsiveness is pure Tailwind,
    // but setting innerWidth costs us nothing and future-proofs.
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      writable: true,
      value: 360,
    })
    render(
      <RatioTrendModal
        open
        onClose={() => {}}
        title="ROE trend"
        suffix="%"
        decimals={1}
        series={SERIES}
        color="green"
      />,
    )
    const panel = getDialogPanel()
    const cls = panel.className
    // Bottom-sheet (mobile, default) classes
    expect(cls).toContain("bottom-0")
    expect(cls).toContain("rounded-t-2xl")
    expect(cls).toContain("left-0")
    expect(cls).toContain("right-0")
    // Must NOT center on the default (mobile) breakpoint — the only
    // centering is via md: prefixed utilities.
    expect(cls).not.toMatch(/(^|\s)-translate-y-1\/2(\s|$)/)
    expect(cls).not.toMatch(/(^|\s)top-1\/2(\s|$)/)
  })

  it("retains md: centered-card classes for desktop", () => {
    render(
      <RatioTrendModal
        open
        onClose={() => {}}
        title="ROE trend"
        suffix="%"
        decimals={1}
        series={SERIES}
        color="green"
      />,
    )
    const cls = getDialogPanel().className
    // Desktop centring via Tailwind md: variants.
    expect(cls).toContain("md:left-1/2")
    expect(cls).toContain("md:top-1/2")
    expect(cls).toContain("md:-translate-x-1/2")
    expect(cls).toContain("md:-translate-y-1/2")
    expect(cls).toContain("md:rounded-2xl")
    // Bottom-pinned anchor is explicitly released at md.
    expect(cls).toContain("md:bottom-auto")
  })
})
