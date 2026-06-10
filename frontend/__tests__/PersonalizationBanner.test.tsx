/**
 * PersonalizationBanner — layout pins for the one-time confirmation
 * strip that renders after a user picks an investing style.
 *
 * Layout regression background (2026-06-11, P1 bug B):
 *   The analysis page mounts <StickyTableOfContents/> as a `xl:block
 *   fixed right-6 w-52` overlay on viewports >= 1280px. With
 *   `flex-wrap` on the banner row and no relative anchor, the
 *   Dismiss button visually broke out of the banner and read NEXT
 *   TO the TOC list ("Dismiss" reading on the "Deep Dive Tabs"
 *   line). The fix establishes a relative flex container with the
 *   Dismiss button as a `shrink-0` sibling of the "Change in
 *   Preferences" prose, capped by a max-width inside the centered
 *   content column. Tests assert the structural invariants so a
 *   future refactor that re-introduces wrap-then-stack on this
 *   row can't ship without flipping a red signal.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen } from "@testing-library/react"
import React from "react"

// next/link → plain anchor for jsdom.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: { href: string; children: React.ReactNode } & Record<string, unknown>) => (
    <a href={href} {...rest}>{children}</a>
  ),
}))

import PersonalizationBanner from "@/components/personalization/PersonalizationBanner"

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  window.localStorage.clear()
})


describe("PersonalizationBanner — self-hide branches", () => {
  it("renders nothing when style is null", () => {
    const { container } = render(<PersonalizationBanner style={null} />)
    expect(container.firstChild).toBeNull()
  })

  it("renders nothing when banner has been dismissed in storage", () => {
    window.localStorage.setItem("yq:personalization-banner-dismissed", "1")
    const { container } = render(<PersonalizationBanner style="beginner" />)
    // useEffect runs synchronously inside render for this component,
    // hidden flips to true and the component returns null on the next
    // render tick. Probing for the role/text is the user-observable
    // assertion.
    expect(container.querySelector("[role='note']")).toBeNull()
  })
})


describe("PersonalizationBanner — render", () => {
  it("renders the banner with style label + Change in Preferences link + Dismiss button", () => {
    render(<PersonalizationBanner style="beginner" />)
    const banner = screen.getByRole("note")
    expect(banner).toBeInTheDocument()

    // Style label text — uses the STYLE_META label, which for
    // "beginner" reads "Beginner". The full prose includes the
    // "Personalised for ..." prefix.
    expect(banner.textContent ?? "").toMatch(/Personalised for/i)
    expect(banner.textContent ?? "").toMatch(/Beginner/i)

    const link = screen.getByRole("link", { name: /change in preferences/i })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute("href", "/account/preferences")

    const dismiss = screen.getByRole("button", { name: /dismiss/i })
    expect(dismiss).toBeInTheDocument()
  })
})


describe("PersonalizationBanner — layout invariants (P1 bug B)", () => {
  // Pin: the Dismiss button must be a DIRECT FLEX SIBLING of the
  // prose <p> that holds the "Change in Preferences" link. If a
  // refactor wraps Dismiss in its own positioning context (absolute,
  // fixed, grid-area outside the row), the document order breaks
  // and on the analysis page the button reads under the right-rail
  // TOC instead of inside the banner. This test asserts the structural
  // sibling relationship; the visual fix lives in the className
  // assertions further down.
  it("Dismiss button is a flex sibling of the Change-in-Preferences prose, not a positioned escape hatch", () => {
    render(<PersonalizationBanner style="beginner" />)
    const banner = screen.getByRole("note")

    const link = screen.getByRole("link", { name: /change in preferences/i })
    const prose = link.closest("p")
    expect(prose).not.toBeNull()
    expect(prose?.parentElement).toBe(banner)

    const dismiss = screen.getByRole("button", { name: /dismiss/i })
    expect(dismiss.parentElement).toBe(banner)

    // Document order: prose comes BEFORE the dismiss button.
    const children = Array.from(banner.children)
    const proseIdx = children.indexOf(prose as Element)
    const dismissIdx = children.indexOf(dismiss)
    expect(proseIdx).toBeGreaterThanOrEqual(0)
    expect(dismissIdx).toBeGreaterThan(proseIdx)
  })

  it("banner row is a positioned flex container, not absolute / fixed", () => {
    render(<PersonalizationBanner style="beginner" />)
    const banner = screen.getByRole("note")
    expect(banner.className).toMatch(/\brelative\b/)
    expect(banner.className).toMatch(/\bflex\b/)
    // Must NOT be position:absolute / position:fixed — those would
    // let the row escape its place in the analysis page flow.
    expect(banner.className).not.toMatch(/\babsolute\b/)
    expect(banner.className).not.toMatch(/\bfixed\b/)
  })

  it("Dismiss button is shrink-0 so the prose cannot push it out of the flex row", () => {
    render(<PersonalizationBanner style="beginner" />)
    const dismiss = screen.getByRole("button", { name: /dismiss/i })
    // shrink-0 (Tailwind) keeps the button from collapsing to 0
    // width when the prose tries to greedy-grow. Equivalent to
    // flex-shrink:0.
    expect(dismiss.className).toMatch(/shrink-0/)
    // And the button itself must NOT be absolute / fixed.
    expect(dismiss.className).not.toMatch(/\babsolute\b/)
    expect(dismiss.className).not.toMatch(/\bfixed\b/)
  })

  it("banner has a max-width cap so it never reaches into the right-rail TOC strip", () => {
    render(<PersonalizationBanner style="beginner" />)
    const banner = screen.getByRole("note")
    expect(banner.className).toMatch(/max-w-/)
  })
})
