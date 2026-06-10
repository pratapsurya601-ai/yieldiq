"use client"

/**
 * SaveNotePanel — per-(user, ticker) research journal.
 *
 * Mounted on the analysis page as a collapsible sidebar surface. Pairs
 * a markdown textarea with a decision-tag chip selector
 * (researching | watching | skipping | owned | sold). Backed by
 * /api/v1/notes/{ticker} — POST is upsert so the auto-save-on-blur
 * path just fires the latest body and lets the service merge.
 *
 * Behaviour
 *   - Anonymous users see a "Sign in to take notes" stub. We do NOT
 *     read or write to a per-tab anon store; notes are intentionally
 *     a logged-in surface (cross-device sync is the whole point).
 *   - Authed users see the composer hydrated from the existing note,
 *     or an empty composer for a first write.
 *   - Tag chips switch immediately and write on blur with the current
 *     textarea body — never silently drop in-progress edits.
 *   - Save status surfaces three transient states: idle, saving,
 *     saved. Errors flip a red toast above the chips with a retry
 *     button; the textarea stays editable so the user does not lose
 *     work to a transient 5xx.
 *   - Delete is gated by an inline confirm; we do not show a modal
 *     for a single-note destruction.
 *
 * SEBI vocabulary
 *   The decision tags are user-private (never rendered to anonymous
 *   surfaces) and are deliberately tense-agnostic ("watching" /
 *   "owned" / "sold"). "Skipping" is the rejected-after-research
 *   state — chosen over "passing" to avoid investment-advice tone.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  DECISION_TAGS,
  type DecisionTag,
  type UserNote,
  deleteNote as deleteNoteApi,
  getNote,
  upsertNote,
} from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { cn } from "@/lib/utils"

interface SaveNotePanelProps {
  ticker: string
  className?: string
  /** Collapsed by default. The analysis page mounts this as a
   *  collapsible surface so it does not crowd the hero on first
   *  paint. Pass `defaultOpen` to flip the initial state for the
   *  /notes index detail view. */
  defaultOpen?: boolean
}

const TAG_LABELS: Record<DecisionTag, string> = {
  researching: "Researching",
  watching: "Watching",
  skipping: "Skipping",
  owned: "Owned",
  sold: "Sold",
}

// Tailwind class bundles per tag. JIT requires the full class strings
// to appear in source — never interpolate at runtime.
const TAG_CHIP_STYLES: Record<
  DecisionTag,
  { active: string; idle: string }
> = {
  researching: {
    active: "bg-brand text-white border-brand",
    idle: "bg-surface text-ink border-border hover:border-brand",
  },
  watching: {
    active: "bg-amber-500 text-white border-amber-500",
    idle: "bg-surface text-ink border-border hover:border-amber-400",
  },
  skipping: {
    active: "bg-neutral-500 text-white border-neutral-500",
    idle: "bg-surface text-ink border-border hover:border-neutral-400",
  },
  owned: {
    active: "bg-emerald-600 text-white border-emerald-600",
    idle: "bg-surface text-ink border-border hover:border-emerald-500",
  },
  sold: {
    active: "bg-rose-600 text-white border-rose-600",
    idle: "bg-surface text-ink border-border hover:border-rose-500",
  },
}

type SaveStatus = "idle" | "saving" | "saved" | "error"

export default function SaveNotePanel({
  ticker,
  className,
  defaultOpen = false,
}: SaveNotePanelProps) {
  const email = useAuthStore((s) => s.email)
  const isAuthed = Boolean(email)

  const [open, setOpen] = useState<boolean>(defaultOpen)
  const [loaded, setLoaded] = useState(false)
  const [content, setContent] = useState("")
  const [tag, setTag] = useState<DecisionTag>("researching")
  const [createdAt, setCreatedAt] = useState<string | null>(null)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const [status, setStatus] = useState<SaveStatus>("idle")
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  // Latest committed body — used by the "Discard" affordance to detect
  // an actual unsaved diff against the server. Without this we'd flag
  // every freshly hydrated note as dirty.
  const lastSavedRef = useRef<string>("")
  const lastSavedTagRef = useRef<DecisionTag>("researching")

  const normalizedTicker = useMemo(
    () => (ticker || "").trim().toUpperCase(),
    [ticker],
  )

  // ── Initial load ─────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    async function hydrate() {
      if (!isAuthed || !normalizedTicker) {
        setLoaded(true)
        return
      }
      try {
        const existing = await getNote(normalizedTicker)
        if (cancelled) return
        if (existing) {
          setContent(existing.content_md ?? "")
          setTag(existing.decision_tag ?? "researching")
          setCreatedAt(existing.created_at)
          setUpdatedAt(existing.updated_at)
          lastSavedRef.current = existing.content_md ?? ""
          lastSavedTagRef.current = existing.decision_tag ?? "researching"
        }
      } catch {
        // Swallow — a hydrate failure shouldn't block the composer.
        // The user can still type and the save path will surface
        // any persistent error.
      } finally {
        if (!cancelled) setLoaded(true)
      }
    }
    void hydrate()
    return () => {
      cancelled = true
    }
  }, [isAuthed, normalizedTicker])

  // ── Save (shared by blur, tag-click, and the explicit Save btn) ──
  const save = useCallback(
    async (overrides?: { content?: string; tag?: DecisionTag }) => {
      if (!isAuthed || !normalizedTicker) return
      const body = overrides?.content ?? content
      const nextTag = overrides?.tag ?? tag
      // Skip the round trip when nothing changed.
      if (
        body === lastSavedRef.current &&
        nextTag === lastSavedTagRef.current
      ) {
        return
      }
      setStatus("saving")
      setErrorMsg(null)
      try {
        const saved: UserNote = await upsertNote(normalizedTicker, {
          content_md: body,
          decision_tag: nextTag,
        })
        lastSavedRef.current = saved.content_md
        lastSavedTagRef.current = saved.decision_tag
        setCreatedAt(saved.created_at)
        setUpdatedAt(saved.updated_at)
        setStatus("saved")
        // Drop the "Saved" pill after a short beat so it doesn't sit
        // on screen forever and read as a permanent banner.
        window.setTimeout(() => {
          setStatus((s) => (s === "saved" ? "idle" : s))
        }, 1800)
      } catch (err: unknown) {
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response
            ?.data?.detail || "Save failed"
        setStatus("error")
        setErrorMsg(String(msg))
      }
    },
    [isAuthed, normalizedTicker, content, tag],
  )

  const handleTagClick = useCallback(
    (next: DecisionTag) => {
      if (!isAuthed) return
      setTag(next)
      void save({ tag: next })
    },
    [isAuthed, save],
  )

  const handleDelete = useCallback(async () => {
    if (!isAuthed || !normalizedTicker) return
    try {
      await deleteNoteApi(normalizedTicker)
      setContent("")
      setTag("researching")
      setCreatedAt(null)
      setUpdatedAt(null)
      lastSavedRef.current = ""
      lastSavedTagRef.current = "researching"
      setConfirmingDelete(false)
      setStatus("idle")
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Delete failed"
      setStatus("error")
      setErrorMsg(String(msg))
    }
  }, [isAuthed, normalizedTicker])

  // ── Render ───────────────────────────────────────────────────
  // Anon stub — kept dead simple. We don't open the composer because
  // we'd have to throw away the body the moment the user signs in,
  // which is a worse experience than asking up-front.
  if (!isAuthed) {
    return (
      <section
        className={cn(
          "rounded-xl border border-border bg-surface p-4",
          className,
        )}
        data-testid="save-note-panel-anon"
      >
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-ink">
            My research notes
          </h3>
          <a
            href="/login"
            className="text-xs font-semibold text-brand hover:underline"
          >
            Sign in
          </a>
        </div>
        <p className="mt-2 text-xs text-caption">
          Sign in to jot a private note for {normalizedTicker} and tag
          where it sits in your research pipeline.
        </p>
      </section>
    )
  }

  return (
    <section
      className={cn(
        "rounded-xl border border-border bg-surface",
        className,
      )}
      data-testid="save-note-panel"
    >
      {/* Header — always visible, doubles as the collapse toggle. */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-2 px-4 py-3 text-left"
        aria-expanded={open}
        aria-controls={`save-note-body-${normalizedTicker}`}
      >
        <div className="flex items-center gap-2 min-w-0">
          <h3 className="text-sm font-semibold text-ink">
            My note on {normalizedTicker}
          </h3>
          {updatedAt && !open && (
            <span className="text-xs text-caption">
              · {TAG_LABELS[tag]}
            </span>
          )}
        </div>
        <span className="text-xs text-caption">
          {open ? "Hide" : "Show"}
        </span>
      </button>

      {open && (
        <div
          id={`save-note-body-${normalizedTicker}`}
          className="px-4 pb-4 pt-1 space-y-3"
        >
          {/* Tag chips */}
          <div className="flex flex-wrap gap-2" role="group" aria-label="Decision tag">
            {DECISION_TAGS.map((t) => {
              const styles = TAG_CHIP_STYLES[t]
              const isActive = t === tag
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => handleTagClick(t)}
                  className={cn(
                    "px-3 py-1.5 text-xs font-semibold rounded-full border transition-colors",
                    isActive ? styles.active : styles.idle,
                  )}
                  aria-pressed={isActive}
                  data-testid={`tag-chip-${t}`}
                >
                  {TAG_LABELS[t]}
                </button>
              )
            })}
          </div>

          {/* Error toast (above the textarea so the user sees it
              without losing context of what they typed). */}
          {status === "error" && errorMsg && (
            <div
              role="alert"
              className="text-xs rounded-md bg-rose-50 text-rose-700 border border-rose-200 px-3 py-2 flex items-center justify-between gap-2 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900"
            >
              <span>{errorMsg}</span>
              <button
                type="button"
                onClick={() => void save()}
                className="font-semibold underline underline-offset-2"
              >
                Retry
              </button>
            </div>
          )}

          {/* Markdown textarea. We don't render the markdown live —
              the AnalyticalNotes panel already proves the pattern of
              storing markdown but rendering plain — keeps focus on
              the user's own words, not pretty styling. */}
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            onBlur={() => void save()}
            placeholder="Why does this look interesting? What would change your mind? Markdown supported."
            rows={6}
            maxLength={50_000}
            disabled={!loaded}
            className={cn(
              "w-full rounded-md border border-border bg-bg p-3 text-sm text-ink",
              "placeholder:text-caption focus:outline-none focus:ring-2 focus:ring-brand/40",
              "font-mono leading-snug resize-y min-h-[120px]",
            )}
            data-testid="save-note-textarea"
          />

          {/* Footer — save status + actions. */}
          <div className="flex items-center justify-between gap-2 text-xs">
            <div className="text-caption" aria-live="polite">
              {status === "saving" && "Saving…"}
              {status === "saved" && "Saved"}
              {status === "idle" && updatedAt && (
                <>Saved {formatRelative(updatedAt)}</>
              )}
              {status === "idle" && !updatedAt && (
                <>Auto-saves when you click away</>
              )}
            </div>
            <div className="flex items-center gap-2">
              {updatedAt && !confirmingDelete && (
                <button
                  type="button"
                  onClick={() => setConfirmingDelete(true)}
                  className="text-xs text-caption hover:text-rose-600"
                  data-testid="delete-note-btn"
                >
                  Delete
                </button>
              )}
              {confirmingDelete && (
                <>
                  <span className="text-xs text-caption">
                    Delete this note?
                  </span>
                  <button
                    type="button"
                    onClick={() => setConfirmingDelete(false)}
                    className="text-xs text-caption hover:text-ink"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDelete()}
                    className="text-xs font-semibold text-rose-600 hover:text-rose-700"
                    data-testid="delete-note-confirm"
                  >
                    Yes, delete
                  </button>
                </>
              )}
              <button
                type="button"
                onClick={() => void save()}
                className="text-xs font-semibold text-brand hover:underline"
                data-testid="save-note-btn"
              >
                Save now
              </button>
            </div>
          </div>

          {createdAt && (
            <p className="text-[11px] text-caption">
              Created {formatRelative(createdAt)} · private to your account
            </p>
          )}
        </div>
      )}
    </section>
  )
}


// ── Helpers ────────────────────────────────────────────────────
// Tiny relative-time formatter. Kept inline rather than added to
// lib/formatters.ts because the only consumer today is this panel
// and the /notes index page — relocate when a third caller exists.
function formatRelative(iso: string): string {
  try {
    const d = new Date(iso)
    const diffMs = Date.now() - d.getTime()
    const sec = Math.max(1, Math.floor(diffMs / 1000))
    if (sec < 60) return `${sec}s ago`
    const min = Math.floor(sec / 60)
    if (min < 60) return `${min}m ago`
    const hr = Math.floor(min / 60)
    if (hr < 24) return `${hr}h ago`
    const day = Math.floor(hr / 24)
    if (day < 30) return `${day}d ago`
    return d.toLocaleDateString()
  } catch {
    return iso
  }
}
