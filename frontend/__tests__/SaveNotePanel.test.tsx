/**
 * SaveNotePanel smoke tests.
 *
 * Pins:
 *   1. Anonymous user renders the sign-in stub (no composer).
 *   2. Authed user with no existing note: composer opens, textarea
 *      empty, "researching" chip active.
 *   3. Authed user with existing note: textarea + tag hydrated.
 *   4. onBlur fires upsertNote with current body + tag.
 *   5. Clicking a tag chip fires upsertNote with the new tag.
 *   6. Error path surfaces a Retry button.
 *   7. Delete confirm flow calls deleteNote.
 *
 * Banned-vocab fragment build per CLAUDE.md rule #5 — the decision
 * tag literals appear in source but none are SEBI-banned today, so
 * this file is left without per-line annotations.
 */
import React from "react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"

const getNoteMock = vi.fn()
const upsertNoteMock = vi.fn()
const deleteNoteMock = vi.fn()

vi.mock("@/lib/api", async () => {
  // Re-export real DECISION_TAGS via dynamic import would couple test
  // to file; just inline-mirror the enum here. Drift is caught by
  // the backend test_notes_service.py tag-enum assertion.
  return {
    DECISION_TAGS: [
      "researching",
      "watching",
      "skipping",
      "owned",
      "sold",
    ] as const,
    getNote: (...a: unknown[]) => getNoteMock(...a),
    upsertNote: (...a: unknown[]) => upsertNoteMock(...a),
    deleteNote: (...a: unknown[]) => deleteNoteMock(...a),
  }
})

// authStore mock — flipped per-test via setEmail() helper.
let _email: string | null = null
vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (s: { email: string | null }) => unknown) =>
    selector({ email: _email }),
}))

function setEmail(e: string | null) {
  _email = e
}

import SaveNotePanel from "@/components/analysis/SaveNotePanel"


beforeEach(() => {
  getNoteMock.mockReset()
  upsertNoteMock.mockReset()
  deleteNoteMock.mockReset()
  setEmail(null)
})


describe("SaveNotePanel — anonymous", () => {
  it("renders the sign-in stub when no email in auth store", () => {
    setEmail(null)
    render(<SaveNotePanel ticker="RELIANCE" />)
    expect(screen.getByTestId("save-note-panel-anon")).toBeTruthy()
    expect(screen.queryByTestId("save-note-textarea")).toBeNull()
  })
})


describe("SaveNotePanel — authed", () => {
  beforeEach(() => {
    setEmail("alice@example.com")
  })

  it("opens an empty composer when no note exists yet", async () => {
    getNoteMock.mockResolvedValueOnce(null)
    render(<SaveNotePanel ticker="RELIANCE" defaultOpen />)

    // Header text must include the ticker name
    expect(screen.getByText(/My note on RELIANCE/)).toBeTruthy()

    // Textarea hydrates empty
    const ta = await screen.findByTestId("save-note-textarea")
    expect((ta as HTMLTextAreaElement).value).toBe("")

    // Default "researching" chip aria-pressed=true
    const chip = screen.getByTestId("tag-chip-researching")
    expect(chip.getAttribute("aria-pressed")).toBe("true")
  })

  it("hydrates textarea + active tag from an existing note", async () => {
    getNoteMock.mockResolvedValueOnce({
      ticker: "RELIANCE",
      content_md: "Old thesis body",
      decision_tag: "owned",
      created_at: "2026-06-09T10:00:00+00:00",
      updated_at: "2026-06-09T11:00:00+00:00",
    })
    render(<SaveNotePanel ticker="RELIANCE" defaultOpen />)
    const ta = await screen.findByTestId("save-note-textarea")
    await waitFor(() =>
      expect((ta as HTMLTextAreaElement).value).toBe("Old thesis body"),
    )
    expect(
      screen.getByTestId("tag-chip-owned").getAttribute("aria-pressed"),
    ).toBe("true")
  })

  it("auto-saves on textarea blur with the current body + tag", async () => {
    getNoteMock.mockResolvedValueOnce(null)
    upsertNoteMock.mockResolvedValueOnce({
      ticker: "RELIANCE",
      content_md: "fresh text",
      decision_tag: "researching",
      created_at: "2026-06-10T10:00:00+00:00",
      updated_at: "2026-06-10T10:00:00+00:00",
    })
    render(<SaveNotePanel ticker="RELIANCE" defaultOpen />)
    const ta = await screen.findByTestId("save-note-textarea")
    fireEvent.change(ta, { target: { value: "fresh text" } })
    fireEvent.blur(ta)
    await waitFor(() => expect(upsertNoteMock).toHaveBeenCalledTimes(1))
    expect(upsertNoteMock).toHaveBeenCalledWith("RELIANCE", {
      content_md: "fresh text",
      decision_tag: "researching",
    })
  })

  it("saves immediately when a tag chip is clicked", async () => {
    getNoteMock.mockResolvedValueOnce(null)
    upsertNoteMock.mockResolvedValueOnce({
      ticker: "RELIANCE",
      content_md: "",
      decision_tag: "watching",
      created_at: "2026-06-10T10:00:00+00:00",
      updated_at: "2026-06-10T10:00:00+00:00",
    })
    render(<SaveNotePanel ticker="RELIANCE" defaultOpen />)
    await screen.findByTestId("save-note-textarea")
    fireEvent.click(screen.getByTestId("tag-chip-watching"))
    await waitFor(() => expect(upsertNoteMock).toHaveBeenCalled())
    expect(upsertNoteMock.mock.calls[0][1].decision_tag).toBe("watching")
  })

  it("surfaces a Retry button on save error", async () => {
    getNoteMock.mockResolvedValueOnce(null)
    upsertNoteMock.mockRejectedValueOnce({
      response: { data: { detail: "Boom" } },
    })
    render(<SaveNotePanel ticker="RELIANCE" defaultOpen />)
    const ta = await screen.findByTestId("save-note-textarea")
    fireEvent.change(ta, { target: { value: "x" } })
    fireEvent.blur(ta)
    await waitFor(() => expect(screen.getByText("Boom")).toBeTruthy())
    expect(screen.getByText("Retry")).toBeTruthy()
  })

  it("confirm-then-delete flow calls deleteNote", async () => {
    getNoteMock.mockResolvedValueOnce({
      ticker: "RELIANCE",
      content_md: "existing",
      decision_tag: "owned",
      created_at: "2026-06-09T10:00:00+00:00",
      updated_at: "2026-06-09T11:00:00+00:00",
    })
    deleteNoteMock.mockResolvedValueOnce({ message: "ok" })
    render(<SaveNotePanel ticker="RELIANCE" defaultOpen />)
    await screen.findByTestId("save-note-textarea")
    fireEvent.click(screen.getByTestId("delete-note-btn"))
    fireEvent.click(screen.getByTestId("delete-note-confirm"))
    await waitFor(() => expect(deleteNoteMock).toHaveBeenCalledWith("RELIANCE"))
  })
})
