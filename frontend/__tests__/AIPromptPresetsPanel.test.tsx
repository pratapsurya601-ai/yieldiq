/**
 * AIPromptPresetsPanel smoke tests.
 *
 * Pins these behaviours (Premium Feel R4):
 *   1. Renders 3 preset cards once the catalogue resolves.
 *   2. Click triggers POST /ai-explain with the correct preset_id.
 *   3. Loading state shows the answer skeleton (matches final shape).
 *   4. Success state expands the card with the answer text + disclaimer.
 *   5. Error state shows a retry button that re-fires the fetch.
 *   6. No SEBI-banned vocab in the rendered DOM (per CLAUDE.md rule #5,
 *      banned vocab list is built from fragments at runtime so the
 *      diff-only sebi-lint check does not flag this file).
 */
import React from "react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

const getAIPresetsMock = vi.fn()
const postAIExplainMock = vi.fn()

vi.mock("@/lib/api", () => ({
  getAIPresets: (...a: unknown[]) => getAIPresetsMock(...a),
  postAIExplain: (...a: unknown[]) => postAIExplainMock(...a),
}))

import AIPromptPresetsPanel from "@/components/analysis/AIPromptPresetsPanel"
import type {
  AIExplainResponse,
  AIPresetsResponse,
} from "@/lib/api"


function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  )
}


const PRESETS_PAYLOAD: AIPresetsResponse = {
  presets: [
    {
      preset_id: "why_value",
      title: "Why does the model see this value?",
      preview:
        "Walk me through the DCF assumptions and what is driving the fair value gap.",
      icon: "lens",
    },
    {
      preset_id: "change_verdict",
      title: "What would change this verdict?",
      preview:
        "If revenue growth slowed to 5% or operating margin compressed, what would the model do?",
      icon: "dial",
    },
    {
      preset_id: "vs_peers",
      title: "How does this compare to its peer cohort?",
      preview:
        "Where does this name rank on score, MoS, and quality within its sector?",
      icon: "grid",
    },
  ],
  disclaimer:
    "AI-generated explanation, educational use only. Not investment advice.",
}


const ANSWER_PAYLOAD: AIExplainResponse = {
  ticker: "HDFCBANK.NS",
  preset_id: "why_value",
  title: "Why does the model see this value?",
  answer:
    "HDFC Bank trades at a 53% discount to the model fair value of Rs 1,146.\n\n" +
    "The DCF uses WACC 9.8% with FCF growth 8% and a 3% terminal rate. " +
    "FCF growth is the single most material lever — open the playground to test it.",
  disclaimer:
    "AI-generated explanation, educational use only. Not investment advice.",
  generated_at: "2026-06-09T10:00:00+05:30",
  model_version: "ai-explain-v1-anthropic-2026-06-09",
  source: "llm_first",
  cached: false,
}


beforeEach(() => {
  getAIPresetsMock.mockReset()
  postAIExplainMock.mockReset()
})


describe("AIPromptPresetsPanel", () => {
  it("renders 3 preset cards once the catalogue resolves", async () => {
    getAIPresetsMock.mockResolvedValue(PRESETS_PAYLOAD)

    renderWithClient(<AIPromptPresetsPanel ticker="HDFCBANK.NS" />)

    // Header is present immediately.
    expect(screen.getByText(/Ask the model/i)).toBeInTheDocument()

    // After the catalogue resolves, all 3 cards mount.
    await waitFor(() => {
      expect(
        screen.getByTestId("ai-preset-card-why_value"),
      ).toBeInTheDocument()
      expect(
        screen.getByTestId("ai-preset-card-change_verdict"),
      ).toBeInTheDocument()
      expect(
        screen.getByTestId("ai-preset-card-vs_peers"),
      ).toBeInTheDocument()
    })

    // Each card shows its title + preview verbatim.
    for (const p of PRESETS_PAYLOAD.presets) {
      expect(screen.getByText(p.title)).toBeInTheDocument()
      expect(screen.getByText(p.preview)).toBeInTheDocument()
    }
  })


  it("click fires POST /ai-explain with the correct preset_id", async () => {
    getAIPresetsMock.mockResolvedValue(PRESETS_PAYLOAD)
    postAIExplainMock.mockResolvedValue(ANSWER_PAYLOAD)

    renderWithClient(<AIPromptPresetsPanel ticker="HDFCBANK.NS" />)

    const cta = await screen.findByTestId("ai-preset-cta-why_value")
    fireEvent.click(cta)

    await waitFor(() => {
      expect(postAIExplainMock).toHaveBeenCalledWith(
        "HDFCBANK.NS",
        "why_value",
      )
    })
  })


  it("loading state shows the answer skeleton", async () => {
    getAIPresetsMock.mockResolvedValue(PRESETS_PAYLOAD)
    // Never resolves -> stays in flight.
    postAIExplainMock.mockReturnValue(
      new Promise(() => { /* never resolves */ }),
    )

    renderWithClient(<AIPromptPresetsPanel ticker="TCS.NS" />)

    const cta = await screen.findByTestId("ai-preset-cta-why_value")
    fireEvent.click(cta)

    await waitFor(() => {
      const skel = screen.getByTestId("ai-answer-skeleton-why_value")
      expect(skel).toBeInTheDocument()
      expect(skel).toHaveAttribute("aria-busy", "true")
    })
    expect(
      screen.queryByTestId("ai-answer-why_value"),
    ).toBeNull()
  })


  it("success state expands the card with answer text + disclaimer", async () => {
    getAIPresetsMock.mockResolvedValue(PRESETS_PAYLOAD)
    postAIExplainMock.mockResolvedValue(ANSWER_PAYLOAD)

    renderWithClient(<AIPromptPresetsPanel ticker="HDFCBANK.NS" />)

    const cta = await screen.findByTestId("ai-preset-cta-why_value")
    fireEvent.click(cta)

    await waitFor(() => {
      expect(screen.getByTestId("ai-answer-why_value")).toBeInTheDocument()
    })

    // First paragraph rendered.
    expect(
      screen.getByText(/53% discount to the model fair value/i),
    ).toBeInTheDocument()
    // Disclaimer rendered (educational only).
    expect(
      screen.getByTestId("ai-answer-disclaimer-why_value"),
    ).toHaveTextContent(/educational use only/i)

    // The CTA button text flips to "Hide answer".
    expect(cta).toHaveTextContent(/Hide answer/i)
  })


  it("error state shows retry button that re-fires the POST", async () => {
    getAIPresetsMock.mockResolvedValue(PRESETS_PAYLOAD)
    postAIExplainMock.mockRejectedValueOnce(new Error("boom"))
    postAIExplainMock.mockResolvedValueOnce(ANSWER_PAYLOAD)

    renderWithClient(<AIPromptPresetsPanel ticker="INFY.NS" />)

    const cta = await screen.findByTestId("ai-preset-cta-why_value")
    fireEvent.click(cta)

    // Error alert renders with the retry control.
    const retry = await screen.findByTestId("ai-answer-retry-why_value")
    expect(retry).toBeInTheDocument()
    expect(
      screen.getByTestId("ai-answer-error-why_value"),
    ).toHaveTextContent(/Could not generate explanation/i)

    fireEvent.click(retry)

    await waitFor(() => {
      expect(screen.getByTestId("ai-answer-why_value")).toBeInTheDocument()
    })
    // Two POSTs total — original + retry.
    expect(postAIExplainMock).toHaveBeenCalledTimes(2)
  })


  it("rendered DOM contains no SEBI-banned vocabulary", async () => {
    getAIPresetsMock.mockResolvedValue(PRESETS_PAYLOAD)
    postAIExplainMock.mockResolvedValue(ANSWER_PAYLOAD)

    const { container } = renderWithClient(
      <AIPromptPresetsPanel ticker="HDFCBANK.NS" />,
    )

    // Trigger an expanded card so the answer text is in the DOM too.
    const cta = await screen.findByTestId("ai-preset-cta-why_value")
    fireEvent.click(cta)
    await waitFor(() => {
      expect(screen.getByTestId("ai-answer-why_value")).toBeInTheDocument()
    })

    // Banned vocab list — built from fragments at runtime per
    // CLAUDE.md rule #5 so the file scans clean for the diff-only
    // sebi-lint check while the runtime assertion stays identical.
    const banned: string[] = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "out" + "perform",
      "under" + "perform",
      "rec" + "ommend",
      "rec" + "ommendation",
      "ac" + "cumulate",
      "ex" + "pensive",
      "ch" + "eap",
      "u" + "ndervalued",
      "ov" + "ervalued",
      "att" + "ractive",
      "po" + "or",
      "str" + "ong",
      "we" + "ak",
      "str" + "ength",
      "wea" + "kness",
      "ap" + "pears",
      "sh" + "ould",
      "con" + "cern",
      "inv" + "estable",
      "inv" + "estability",
    ]

    const dom = (container.textContent || "").toLowerCase()
    for (const word of banned) {
      const re = new RegExp(`\\b${word}\\b`)
      expect(dom).not.toMatch(re)
    }
  })
})
