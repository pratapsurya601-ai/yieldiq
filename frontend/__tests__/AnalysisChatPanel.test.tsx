/**
 * AnalysisChatPanel smoke tests.
 *
 * Pins these behaviours (T6.2 Phase A):
 *   1. Launcher button toggles the slide-in drawer.
 *   2. Send triggers postChatStream with the ticker + the user
 *      message (NOT the empty assistant placeholder).
 *   3. Streaming deltas assemble in the assistant bubble live —
 *      partial text lands before the done:true event.
 *   4. Suggested-prompt chip pre-populates the textarea.
 *   5. Cmd+Enter submits the composer.
 *   6. SEBI guard — no banned vocab in the rendered DOM (banned
 *      list built from fragments per CLAUDE.md rule #5).
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

import AnalysisChatPanel from "@/components/analysis/AnalysisChatPanel"
import type { ChatStreamEvent } from "@/lib/api"


beforeEach(() => {
  postChatStreamMock.mockReset()
})


function openDrawer() {
  const launcher = screen.getByTestId("analysis-chat-launcher")
  fireEvent.click(launcher)
}


describe("AnalysisChatPanel", () => {
  it("launcher toggles the drawer aria-hidden state", () => {
    render(<AnalysisChatPanel ticker="HDFCBANK.NS" />)

    const drawer = screen.getByTestId("analysis-chat-panel")
    expect(drawer).toHaveAttribute("aria-hidden", "true")

    openDrawer()
    expect(drawer).toHaveAttribute("aria-hidden", "false")

    // Close button hides the drawer again.
    fireEvent.click(screen.getByTestId("analysis-chat-close"))
    expect(drawer).toHaveAttribute("aria-hidden", "true")
  })


  it("send fires postChatStream with the user message only", async () => {
    postChatStreamMock.mockImplementation(
      async ({ onEvent }: { onEvent: (e: ChatStreamEvent) => void }) => {
        onEvent({ delta: "Hello.", done: false })
        onEvent({ delta: "", done: true })
      },
    )

    render(<AnalysisChatPanel ticker="HDFCBANK.NS" />)
    openDrawer()

    const input = screen.getByTestId("analysis-chat-input") as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: "What is the MoS?" } })

    fireEvent.click(screen.getByTestId("analysis-chat-send"))

    await waitFor(() => {
      expect(postChatStreamMock).toHaveBeenCalledTimes(1)
    })

    const args = postChatStreamMock.mock.calls[0][0]
    expect(args.ticker).toBe("HDFCBANK.NS")
    expect(args.messages).toEqual([
      { role: "user", content: "What is the MoS?" },
    ])
  })


  it("assembles streaming deltas into the assistant bubble", async () => {
    let dispatch: (ev: ChatStreamEvent) => void = () => {}
    postChatStreamMock.mockImplementation(
      ({ onEvent }: { onEvent: (e: ChatStreamEvent) => void }) => {
        dispatch = onEvent
        return new Promise<void>((resolve) => {
          // Resolve when the test signals completion.
          ;(dispatch as unknown as { resolve: () => void }).resolve = resolve
        })
      },
    )

    render(<AnalysisChatPanel ticker="TCS.NS" />)
    openDrawer()

    fireEvent.change(screen.getByTestId("analysis-chat-input"), {
      target: { value: "Why this verdict?" },
    })
    fireEvent.click(screen.getByTestId("analysis-chat-send"))

    await waitFor(() => {
      expect(postChatStreamMock).toHaveBeenCalled()
    })

    // Stream the first delta.
    await act(async () => {
      dispatch({ delta: "The model ", done: false })
    })
    await waitFor(() => {
      expect(screen.getByTestId("analysis-chat-message-1")).toHaveTextContent(
        /The model/,
      )
    })

    // Stream the second delta — the bubble's text appends.
    await act(async () => {
      dispatch({ delta: "lands at fair value Rs 1,146.", done: false })
    })
    await waitFor(() => {
      expect(screen.getByTestId("analysis-chat-message-1")).toHaveTextContent(
        /Rs 1,146/,
      )
    })

    // done:true releases the streaming pulse / cursor.
    await act(async () => {
      dispatch({ delta: "", done: true })
    })
  })


  it("clicking a suggested prompt populates the textarea", () => {
    render(<AnalysisChatPanel ticker="INFY.NS" />)
    openDrawer()

    const chip = screen.getByTestId("analysis-chat-suggestion-0")
    fireEvent.click(chip)

    const input = screen.getByTestId("analysis-chat-input") as HTMLTextAreaElement
    expect(input.value.length).toBeGreaterThan(10)
  })


  it("Cmd+Enter submits the composer", async () => {
    postChatStreamMock.mockImplementation(
      async ({ onEvent }: { onEvent: (e: ChatStreamEvent) => void }) => {
        onEvent({ delta: "ok.", done: true })
      },
    )

    render(<AnalysisChatPanel ticker="RELIANCE.NS" />)
    openDrawer()

    const input = screen.getByTestId("analysis-chat-input") as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: "Ping." } })
    fireEvent.keyDown(input, { key: "Enter", metaKey: true })

    await waitFor(() => {
      expect(postChatStreamMock).toHaveBeenCalledTimes(1)
    })
  })


  it("rendered DOM contains no SEBI-banned vocabulary", async () => {
    // Even when the model streams adversarial deltas (the backend
    // scrubs but the component must also not paint banned
    // tokens in its own copy: header, placeholder, suggested prompts,
    // empty state).
    postChatStreamMock.mockImplementation(
      async ({ onEvent }: { onEvent: (e: ChatStreamEvent) => void }) => {
        onEvent({ delta: "A clean reply.", done: true })
      },
    )

    const { container } = render(
      <AnalysisChatPanel ticker="HDFCBANK.NS" />,
    )
    openDrawer()

    fireEvent.change(screen.getByTestId("analysis-chat-input"), {
      target: { value: "Walk me through the model output." },
    })
    fireEvent.click(screen.getByTestId("analysis-chat-send"))

    await waitFor(() => {
      expect(screen.getByTestId("analysis-chat-message-1")).toBeInTheDocument()
    })

    // Per CLAUDE.md rule #5: banned vocab list built from fragments
    // at runtime so the diff-only sebi-lint check does not flag this
    // file. The runtime assertion is unchanged.
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
})
