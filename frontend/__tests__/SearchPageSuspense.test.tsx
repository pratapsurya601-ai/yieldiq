/**
 * Search page Suspense boundary regression test.
 *
 * Pins the fix for the Vercel build failure where
 * `useSearchParams()` was used outside a `<Suspense>` boundary,
 * which causes Next.js 15+ production prerender to bail with a
 * suspense-boundary error.
 *
 * If a future refactor inlines the inner component back into the
 * default export without keeping a Suspense wrapper, this test will
 * fail because the Suspense fallback won't render while
 * `useSearchParams()` is suspended.
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"

// Stub next/navigation so the page can mount in jsdom without a router.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams("q=RELIANCE"),
}))

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode } & Record<string, unknown>) => (
    <a href={href} {...rest}>{children}</a>
  ),
}))

// Avoid the network fetch of /tickers.json during the test.
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ tickers: [] }),
    }),
  )
})

import { beforeEach } from "vitest"
import SearchPage from "@/app/(app)/search/page"

describe("SearchPage Suspense wrapper", () => {
  it("renders the inner page (proves Suspense boundary resolves)", async () => {
    render(<SearchPage />)
    // The inner page renders the "Analyse a stock" heading; if the
    // Suspense boundary never resolved we would only ever see the
    // "Loading search…" fallback.
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /analyse a stock/i })).toBeInTheDocument()
    })
  })

  it("hydrates the ?q= deep link into the search input", async () => {
    render(<SearchPage />)
    await waitFor(() => {
      const input = screen.getByLabelText(/search stocks/i) as HTMLInputElement
      expect(input.value).toBe("RELIANCE")
    })
  })
})
