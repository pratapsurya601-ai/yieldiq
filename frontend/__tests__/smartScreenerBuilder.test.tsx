/**
 * Smart Screener (composite criteria) — builder page unit tests.
 *
 * Covers:
 *   1. Empty state renders when no criteria + no sector + no run flag.
 *   2. Add-criterion adds a row; remove-criterion drops it.
 *   3. Sector dropdown change triggers the live count query.
 *   4. Encoded ?c= param decodes into editable criteria on mount.
 *   5. Share writes the encoded URL to the clipboard.
 *
 * We mock axios `api`, next/navigation, and the clipboard. We do NOT
 * boot a real network — every API call resolves to a synthetic
 * payload shaped like the real /smart and /smart/count + /smart/fields
 * responses so the React Query layer hydrates without surprises.
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import React from "react"

let currentSearch = new URLSearchParams()
const mockReplace = vi.fn()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/screener/builder",
  useSearchParams: () => currentSearch,
}))

// ModelDisclaimer is a pure presentational component — stub to keep
// the test tree small and avoid pulling its dependency graph.
vi.mock("@/components/ModelDisclaimer", () => ({
  default: () => <div data-testid="model-disclaimer-stub" />,
}))

// API mock. We dispatch on URL so /smart/fields, /smart/count, and
// /smart can return different fixtures from a single mocked module.
const mockGet = vi.fn()
const mockPost = vi.fn()
vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
  },
}))

const FIELDS_FIXTURE = {
  fields: [
    { key: "mos", label: "Margin of Safety %", type: "number" },
    { key: "roe", label: "ROE %", type: "number" },
    { key: "dividend_streak_years", label: "Dividend streak (years)", type: "number" },
    { key: "sbc_intensity_label", label: "SBC intensity", type: "string" },
    { key: "moat", label: "Moat", type: "string" },
  ],
  ops: { number: ["<", "<=", "=", "!=", ">", ">="], string: ["=", "!=", "in", "not_in"] },
  sort_keys: ["mos", "roe", "dividend_streak_years"],
}

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

// Import after mocks so the page picks up the mocked next/navigation.
async function loadPage() {
  const mod = await import("@/app/(app)/screener/builder/page")
  return mod.default
}

beforeEach(() => {
  currentSearch = new URLSearchParams()
  mockReplace.mockReset()
  mockGet.mockReset()
  mockPost.mockReset()

  mockGet.mockImplementation(async (url: string) => {
    if (url.includes("/screener/smart/fields")) {
      return { data: FIELDS_FIXTURE }
    }
    return { data: {} }
  })
  mockPost.mockImplementation(async (url: string) => {
    if (url.includes("/screener/smart/count")) {
      return { data: { count: 12, sector: null } }
    }
    if (url.endsWith("/screener/smart")) {
      return {
        data: {
          matches: [
            {
              ticker: "ITC.NS",
              score: 71,
              mos: 22.5,
              fair_value_ratio: 1.29,
              pe_ratio: 18.4,
              roe: 26.1,
              sector: "FMCG",
              verdict: "undervalued",
            },
          ],
          count: 1,
          summary: { count: 1, median_mos: 22.5, median_score: 71, median_roe: 26.1 },
          sector: "FMCG",
          sort: "mos",
          limit: 100,
        },
      }
    }
    return { data: {} }
  })
})

describe("Smart Screener builder", () => {
  it("renders empty-state hint when no sector and no criteria yet", async () => {
    const Page = await loadPage()
    const Wrapper = makeWrapper()
    render(
      <Wrapper>
        <Page />
      </Wrapper>,
    )
    expect(await screen.findByTestId("smart-builder")).toBeTruthy()
    expect(screen.getByTestId("smart-empty")).toBeTruthy()
  })

  it("adds and removes criterion rows", async () => {
    const Page = await loadPage()
    const Wrapper = makeWrapper()
    render(
      <Wrapper>
        <Page />
      </Wrapper>,
    )
    await screen.findByTestId("smart-builder")
    // Initial state seeds one blank row.
    let rows = screen.getAllByTestId("smart-criterion-row")
    expect(rows.length).toBe(1)

    fireEvent.click(screen.getByText("+ Add criterion"))
    rows = screen.getAllByTestId("smart-criterion-row")
    expect(rows.length).toBe(2)

    // Remove the second row.
    const removeButtons = screen.getAllByLabelText("Remove criterion")
    fireEvent.click(removeButtons[1])
    rows = screen.getAllByTestId("smart-criterion-row")
    expect(rows.length).toBe(1)
  })

  it("decodes ?c= URL param into criteria on mount", async () => {
    // base64url("[{\"field\":\"mos\",\"op\":\">\",\"value\":\"20\"}]")
    const json = '[{"field":"mos","op":">","value":"20"}]'
    const b64 = Buffer.from(json, "utf-8").toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
    currentSearch = new URLSearchParams({ c: b64, sector: "FMCG" })

    const Page = await loadPage()
    const Wrapper = makeWrapper()
    render(
      <Wrapper>
        <Page />
      </Wrapper>,
    )
    await screen.findByTestId("smart-builder")
    // Sector dropdown should reflect the URL.
    expect((screen.getByTestId("smart-sector") as HTMLSelectElement).value).toBe("FMCG")
    // One decoded row should appear with the value pre-populated.
    const valueInputs = screen.getAllByLabelText("Criterion value") as HTMLInputElement[]
    expect(valueInputs[0].value).toBe("20")
  })

  it("fires the live count POST when a sector is picked", async () => {
    const Page = await loadPage()
    const Wrapper = makeWrapper()
    render(
      <Wrapper>
        <Page />
      </Wrapper>,
    )
    await screen.findByTestId("smart-builder")
    const sectorSelect = screen.getByTestId("smart-sector") as HTMLSelectElement
    await act(async () => {
      fireEvent.change(sectorSelect, { target: { value: "FMCG" } })
    })
    await waitFor(() => {
      const calls = mockPost.mock.calls.filter((c) => String(c[0]).includes("/smart/count"))
      expect(calls.length).toBeGreaterThan(0)
    })
  })

  it("writes the share URL to clipboard on Share click", async () => {
    // Seed criteria so the Share button is enabled.
    const json = '[{"field":"mos","op":">","value":"20"}]'
    const b64 = Buffer.from(json, "utf-8").toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
    currentSearch = new URLSearchParams({ c: b64, sector: "FMCG" })

    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(window.navigator, "clipboard", {
      value: { writeText },
      writable: true,
      configurable: true,
    })

    const Page = await loadPage()
    const Wrapper = makeWrapper()
    render(
      <Wrapper>
        <Page />
      </Wrapper>,
    )
    await screen.findByTestId("smart-builder")
    await act(async () => {
      fireEvent.click(screen.getByTestId("smart-share"))
    })
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledTimes(1)
      const url = String(writeText.mock.calls[0][0])
      expect(url).toContain("/screener/builder")
      expect(url).toContain("sector=FMCG")
      expect(url).toContain("c=")
    })
  })
})
