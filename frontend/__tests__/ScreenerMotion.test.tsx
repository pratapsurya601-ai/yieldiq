/**
 * Screener motion wiring smoke test.
 *
 * Pins the integration of the motion primitives library on the screener
 * empty-state preset picker. Specifically:
 *   1. The preset-card grid is wrapped in a <RevealStagger> — emits
 *      `data-anim="reveal-stagger"` on its outer container.
 *   2. Each preset card is wrapped in <HoverCard> — emits
 *      `data-motion="hover-card"`.
 *   3. The "build from scratch" link is wrapped in <PressScale> —
 *      emits `data-motion="press-scale"`.
 *
 * Why a wiring test rather than animation behavior? The motion
 * components own their reduced-motion + timing logic; we test those
 * inside the motion package. This test exists to catch a regression
 * where someone unwraps a primitive while refactoring this page.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

let currentSearch = new URLSearchParams()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/screener",
  useSearchParams: () => currentSearch,
}))

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string
    children: React.ReactNode
  } & Record<string, unknown>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

vi.mock("@/lib/api", () => {
  const getMock = vi.fn(async (url: string) => {
    if (url.includes("/screener/fields")) {
      return {
        data: {
          fields: [{ key: "roe", label: "ROE", type: "numeric", unit: "%" }],
          sortable: ["roe"],
        },
      }
    }
    return { data: {} }
  })
  return {
    default: { get: getMock, post: vi.fn() },
    BUILD_ID: "test",
  }
})

import ScreenerPage from "@/app/(app)/screener/page"

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  currentSearch = new URLSearchParams()
})

describe("Screener page motion wiring", () => {
  it("wraps the preset grid in RevealStagger + each card in HoverCard", async () => {
    currentSearch = new URLSearchParams()
    const { container } = renderWithClient(<ScreenerPage />)

    await waitFor(() => {
      expect(
        container.querySelector("[data-anim='reveal-stagger']"),
      ).toBeInTheDocument()
    })

    // At least one preset tile now carries the HoverCard marker.
    const hoverCards = container.querySelectorAll("[data-motion='hover-card']")
    expect(hoverCards.length).toBeGreaterThan(0)
  })

  it("wraps the 'build from scratch' link in PressScale", async () => {
    currentSearch = new URLSearchParams()
    const { container } = renderWithClient(<ScreenerPage />)

    await waitFor(() => {
      // PressScale uses data-motion="press-scale" on its wrapper.
      expect(
        container.querySelector("[data-motion='press-scale']"),
      ).toBeInTheDocument()
    })
  })
})
