/**
 * AnalysisPromptPresets — competitor audit #4 quick-action panel.
 *
 * Pins these behaviours:
 *   1. Both preset cards render with their title + description.
 *   2. Clicking a card invokes postChatStream with the ticker plus a
 *      single pre-baked user message produced by the promptBuilder.
 *   3. Streaming deltas land inside the response panel live (partial
 *      text visible before done:true).
 *   4. done:true releases the streaming cursor.
 *   5. The 429 path surfaces an upgrade CTA instead of the answer body.
 *   6. When required engine numbers are missing the card surfaces a
 *      static empty-state and never calls postChatStream.
 *   7. SEBI guard — neither the static copy nor the streamed answer
 *      ever paints banned vocabulary in the rendered DOM (banned list
 *      assembled from fragments per CLAUDE.md rule #5).
 *   8. A second card click cancels the first request's AbortController.
 */
import React from "react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import {
  render,
  screen,
  waitFor,
  fireEvent,
  act,
} from "@testing-library/react"

const postChatStreamMock = vi.fn()

vi.mock("@/lib/api", () => ({
  postChatStream: (...a: unknown[]) => postChatStreamMock(...a),
}))

import AnalysisPromptPresets from "@/components/analysis/AnalysisPromptPresets"
import type { AnalysisResponse } from "@/types/api"
import type { ChatStreamEvent } from "@/lib/api"


// Minimal AnalysisResponse fixture — only the fields the promptBuilders
// touch are populated; everything else is cast through `unknown` so the
// test does not have to mirror the whole 700-field type surface.
function makeData(overrides: Partial<AnalysisResponse> = {}): AnalysisResponse {
  const base = {
    ticker: "HDFCBANK.NS",
    composite_intrinsic_value: 1850,
    multiples_based_fv: 1620,
    valuation: {
      fair_value: 1746,
      current_price: 1500,
      margin_of_safety: 14,
    },
    analyst_consensus: {
      coverage_count: 27,
      price_target: { mean: 1980, median: 1950, high: 2200, low: 1700, vs_current_pct: 32 },
    },
  } as unknown as AnalysisResponse
  return { ...base, ...overrides } as AnalysisResponse
}


beforeEach(() => {
  postChatStreamMock.mockReset()
})


describe("AnalysisPromptPresets", () => {
  it("renders both preset cards with title + description", () => {
    render(<AnalysisPromptPresets data={makeData()} />)

    expect(screen.getByTestId("analysis-prompt-presets")).toBeInTheDocument()
    expect(
      screen.getByTestId("analysis-prompt-preset-card-why_valued"),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId("analysis-prompt-preset-card-platforms_compare"),
    ).toBeInTheDocument()
    expect(screen.getByText(/Why is this valued this way/i)).toBeInTheDocument()
    expect(
      screen.getByText(/What do other platforms think/i),
    ).toBeInTheDocument()
  })


  it("clicking the 'why valued' card fires postChatStream with a grounded prompt", async () => {
    postChatStreamMock.mockImplementation(
      async ({ onEvent }: { onEvent: (e: ChatStreamEvent) => void }) => {
        onEvent({ delta: "ok.", done: true })
      },
    )

    render(<AnalysisPromptPresets data={makeData()} />)
    fireEvent.click(
      screen.getByTestId("analysis-prompt-preset-card-why_valued"),
    )

    await waitFor(() => {
      expect(postChatStreamMock).toHaveBeenCalledTimes(1)
    })

    const args = postChatStreamMock.mock.calls[0][0]
    expect(args.ticker).toBe("HDFCBANK.NS")
    expect(Array.isArray(args.messages)).toBe(true)
    expect(args.messages).toHaveLength(1)
    expect(args.messages[0].role).toBe("user")
    // Prompt must embed the actual engine numbers, not placeholders.
    const prompt: string = args.messages[0].content
    expect(prompt).toContain("HDFCBANK.NS")
    expect(prompt).toContain("1,850") // composite IV, INR-formatted
    expect(prompt).toContain("1,746") // DCF fair value
    expect(prompt.toLowerCase()).toContain("plain english")
  })


  it("assembles streaming deltas into the response panel live", async () => {
    let dispatch: (ev: ChatStreamEvent) => void = () => {}
    postChatStreamMock.mockImplementation(
      ({ onEvent }: { onEvent: (e: ChatStreamEvent) => void }) => {
        dispatch = onEvent
        return new Promise<void>(() => {
          // Never resolves — the test ends the stream via dispatch().
        })
      },
    )

    render(<AnalysisPromptPresets data={makeData()} />)
    fireEvent.click(
      screen.getByTestId("analysis-prompt-preset-card-platforms_compare"),
    )

    await waitFor(() => {
      expect(postChatStreamMock).toHaveBeenCalled()
    })

    await act(async () => {
      dispatch({ delta: "Wall Street ", done: false })
    })
    await waitFor(() => {
      expect(
        screen.getByTestId("analysis-prompt-presets-text"),
      ).toHaveTextContent(/Wall Street/)
    })

    await act(async () => {
      dispatch({ delta: "uses a longer fade.", done: false })
    })
    await waitFor(() => {
      expect(
        screen.getByTestId("analysis-prompt-presets-text"),
      ).toHaveTextContent(/longer fade/)
    })

    // The streaming cursor stays visible until done:true.
    expect(
      screen.getByTestId("analysis-prompt-presets-cursor"),
    ).toBeInTheDocument()

    await act(async () => {
      dispatch({ delta: "", done: true })
    })
    // Cursor goes away once streaming is complete.
    await waitFor(() => {
      expect(
        screen.queryByTestId("analysis-prompt-presets-cursor"),
      ).not.toBeInTheDocument()
    })
  })


  it("surfaces the 429 daily-limit message instead of an answer", async () => {
    const err = new Error("chat stream failed: 429") as Error & { status?: number }
    err.status = 429
    postChatStreamMock.mockRejectedValue(err)

    render(<AnalysisPromptPresets data={makeData()} />)
    fireEvent.click(
      screen.getByTestId("analysis-prompt-preset-card-why_valued"),
    )

    await waitFor(() => {
      expect(
        screen.getByTestId("analysis-prompt-presets-error"),
      ).toBeInTheDocument()
    })
    expect(
      screen.getByTestId("analysis-prompt-presets-error").textContent || "",
    ).toMatch(/daily ai limit/i)
  })


  it("disables outbound call when required engine numbers are missing", async () => {
    const data = makeData({
      composite_intrinsic_value: null,
    } as unknown as Partial<AnalysisResponse>)

    render(<AnalysisPromptPresets data={data} />)
    fireEvent.click(
      screen.getByTestId("analysis-prompt-preset-card-why_valued"),
    )

    await waitFor(() => {
      expect(
        screen.getByTestId("analysis-prompt-presets-error"),
      ).toBeInTheDocument()
    })
    expect(postChatStreamMock).not.toHaveBeenCalled()
  })


  it("clicking a second card aborts the in-flight request", async () => {
    const seenSignals: AbortSignal[] = []
    postChatStreamMock.mockImplementation(
      ({ signal }: { signal: AbortSignal }) => {
        seenSignals.push(signal)
        return new Promise<void>(() => {
          // Never resolves — keep the stream "in flight".
        })
      },
    )

    render(<AnalysisPromptPresets data={makeData()} />)
    fireEvent.click(
      screen.getByTestId("analysis-prompt-preset-card-why_valued"),
    )
    await waitFor(() => {
      expect(postChatStreamMock).toHaveBeenCalledTimes(1)
    })

    fireEvent.click(
      screen.getByTestId("analysis-prompt-preset-card-platforms_compare"),
    )
    await waitFor(() => {
      expect(postChatStreamMock).toHaveBeenCalledTimes(2)
    })

    expect(seenSignals[0].aborted).toBe(true)
    expect(seenSignals[1].aborted).toBe(false)
  })


  it("rendered DOM contains no SEBI-banned vocabulary", async () => {
    postChatStreamMock.mockImplementation(
      async ({ onEvent }: { onEvent: (e: ChatStreamEvent) => void }) => {
        // Backend stream itself is SEBI-clean; the component must
        // not paint banned tokens via its own static copy either
        // (header, descriptions, button labels, disclaimer).
        onEvent({ delta: "A clean explanation of the model output.", done: true })
      },
    )

    const { container } = render(<AnalysisPromptPresets data={makeData()} />)
    fireEvent.click(
      screen.getByTestId("analysis-prompt-preset-card-why_valued"),
    )
    await waitFor(() => {
      expect(
        screen.getByTestId("analysis-prompt-presets-text"),
      ).toBeInTheDocument()
    })

    // Per CLAUDE.md rule #5: build the banned list from fragments at
    // runtime so the diff-only sebi-lint check does not flag this
    // file. Runtime assertion is unchanged.
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
    ]
    const dom = (container.textContent || "").toLowerCase()
    for (const word of banned) {
      const re = new RegExp(`\\b${word}\\b`)
      expect(dom).not.toMatch(re)
    }
  })


  it("re-running the same card resets the response text", async () => {
    let dispatch: (ev: ChatStreamEvent) => void = () => {}
    postChatStreamMock.mockImplementation(
      ({ onEvent }: { onEvent: (e: ChatStreamEvent) => void }) => {
        dispatch = onEvent
        return new Promise<void>(() => {})
      },
    )

    render(<AnalysisPromptPresets data={makeData()} />)
    fireEvent.click(
      screen.getByTestId("analysis-prompt-preset-card-why_valued"),
    )
    await waitFor(() => {
      expect(postChatStreamMock).toHaveBeenCalledTimes(1)
    })
    await act(async () => {
      dispatch({ delta: "first answer fragment.", done: false })
    })
    await waitFor(() => {
      expect(
        screen.getByTestId("analysis-prompt-presets-text"),
      ).toHaveTextContent(/first answer/)
    })

    // Click the same card a second time — the response panel must // sebi-allow: should
    // reset before the new stream starts (no stale concatenation).
    fireEvent.click(
      screen.getByTestId("analysis-prompt-preset-card-why_valued"),
    )
    await waitFor(() => {
      expect(postChatStreamMock).toHaveBeenCalledTimes(2)
    })
    await waitFor(() => {
      const text =
        screen.getByTestId("analysis-prompt-presets-text").textContent || ""
      expect(text.toLowerCase()).not.toContain("first answer")
    })
  })
})
