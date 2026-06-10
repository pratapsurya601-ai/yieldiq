"use client"

/**
 * /notes — cross-ticker notes index.
 *
 * Lists every note the signed-in user has written, newest-first by
 * updated_at. Chip selector at the top narrows by decision tag
 * (researching | watching | skipping | owned | sold).
 *
 * Each row links to /analysis/{ticker} so the user can hop straight
 * back into the deep-dive that the note was written against. The
 * SaveNotePanel mounted there will hydrate from the same backend row
 * so the note is the same body on both surfaces.
 *
 * Not a SaveNotePanel container — that lives on the analysis page.
 * This page is the audit/review surface; editing happens inline on
 * the ticker context.
 */

import Link from "next/link"
import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  DECISION_TAGS,
  type DecisionTag,
  type UserNote,
  listNotes,
} from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { cn } from "@/lib/utils"

const ALL_TAG_LABEL = "All"
const TAG_LABELS: Record<DecisionTag, string> = {
  researching: "Researching",
  watching: "Watching",
  skipping: "Skipping",
  owned: "Owned",
  sold: "Sold",
}

// Mirror SaveNotePanel's chip palette so the same tag colours appear
// in both places — keeps the visual association tight.
const TAG_CHIP_STYLES: Record<
  DecisionTag,
  { active: string; idle: string; dot: string }
> = {
  researching: {
    active: "bg-brand text-white border-brand",
    idle: "bg-surface text-ink border-border hover:border-brand",
    dot: "bg-brand",
  },
  watching: {
    active: "bg-amber-500 text-white border-amber-500",
    idle: "bg-surface text-ink border-border hover:border-amber-400",
    dot: "bg-amber-500",
  },
  skipping: {
    active: "bg-neutral-500 text-white border-neutral-500",
    idle: "bg-surface text-ink border-border hover:border-neutral-400",
    dot: "bg-neutral-500",
  },
  owned: {
    active: "bg-emerald-600 text-white border-emerald-600",
    idle: "bg-surface text-ink border-border hover:border-emerald-500",
    dot: "bg-emerald-600",
  },
  sold: {
    active: "bg-rose-600 text-white border-rose-600",
    idle: "bg-surface text-ink border-border hover:border-rose-500",
    dot: "bg-rose-600",
  },
}

export default function NotesIndexPage() {
  const email = useAuthStore((s) => s.email)
  const isAuthed = Boolean(email)
  const [activeTag, setActiveTag] = useState<DecisionTag | null>(null)

  const query = useQuery<UserNote[]>({
    queryKey: ["notes", "list", activeTag ?? "all"],
    queryFn: () => listNotes(activeTag),
    enabled: isAuthed,
    staleTime: 30_000,
  })

  // Per-tag counts driven off the unfiltered fetch when no chip is
  // active. When a chip IS active the query is already filtered so we
  // don't have the cross-tag counts — show only the active count.
  const counts = useMemo<Record<DecisionTag | "all", number>>(() => {
    const empty: Record<DecisionTag | "all", number> = {
      all: 0,
      researching: 0,
      watching: 0,
      skipping: 0,
      owned: 0,
      sold: 0,
    }
    if (!query.data) return empty
    if (activeTag) {
      empty.all = query.data.length
      empty[activeTag] = query.data.length
      return empty
    }
    empty.all = query.data.length
    for (const n of query.data) {
      empty[n.decision_tag as DecisionTag] += 1
    }
    return empty
  }, [query.data, activeTag])

  if (!isAuthed) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-10 text-center">
        <h1 className="text-2xl font-semibold text-ink">Your research notes</h1>
        <p className="mt-3 text-sm text-caption">
          Sign in to see every note you have taken across tickers, filterable
          by where each idea sits in your research pipeline.
        </p>
        <Link
          href="/login"
          className="mt-6 inline-block rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand/90"
        >
          Sign in
        </Link>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold text-ink">Your research notes</h1>
        <p className="text-sm text-caption">
          Private to your account. Click any note to jump back into the
          analysis page for that ticker.
        </p>
      </header>

      {/* Chip selector */}
      <div
        className="flex flex-wrap gap-2"
        role="group"
        aria-label="Filter notes by decision tag"
      >
        <button
          type="button"
          onClick={() => setActiveTag(null)}
          className={cn(
            "px-3 py-1.5 text-xs font-semibold rounded-full border transition-colors",
            activeTag === null
              ? "bg-ink text-white border-ink"
              : "bg-surface text-ink border-border hover:border-ink",
          )}
          aria-pressed={activeTag === null}
        >
          {ALL_TAG_LABEL}
          <span className="ml-1.5 opacity-80">({counts.all})</span>
        </button>
        {DECISION_TAGS.map((t) => {
          const styles = TAG_CHIP_STYLES[t]
          const isActive = activeTag === t
          return (
            <button
              key={t}
              type="button"
              onClick={() => setActiveTag(t)}
              className={cn(
                "px-3 py-1.5 text-xs font-semibold rounded-full border transition-colors",
                isActive ? styles.active : styles.idle,
              )}
              aria-pressed={isActive}
              data-testid={`filter-chip-${t}`}
            >
              {TAG_LABELS[t]}
              <span className="ml-1.5 opacity-80">({counts[t]})</span>
            </button>
          )
        })}
      </div>

      {/* Body */}
      {query.isLoading && (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-24 rounded-xl border border-border bg-surface animate-pulse"
            />
          ))}
        </div>
      )}

      {query.isError && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900">
          Could not load notes.{" "}
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="font-semibold underline underline-offset-2"
          >
            Retry
          </button>
        </div>
      )}

      {!query.isLoading && !query.isError && (query.data ?? []).length === 0 && (
        <EmptyState activeTag={activeTag} />
      )}

      {!query.isLoading && (query.data ?? []).length > 0 && (
        <ul className="space-y-3" data-testid="notes-list">
          {(query.data ?? []).map((n) => (
            <NoteRow key={n.ticker} note={n} />
          ))}
        </ul>
      )}
    </div>
  )
}


function NoteRow({ note }: { note: UserNote }) {
  const styles = TAG_CHIP_STYLES[note.decision_tag as DecisionTag]
  return (
    <li>
      <Link
        href={`/analysis/${encodeURIComponent(note.ticker)}#notes`}
        className="block rounded-xl border border-border bg-surface p-4 hover:border-brand transition-colors"
        data-testid={`note-row-${note.ticker}`}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={cn("inline-block w-2 h-2 rounded-full", styles.dot)}
              aria-hidden="true"
            />
            <span className="text-sm font-semibold text-ink">
              {note.ticker}
            </span>
            <span className="text-xs text-caption">
              · {TAG_LABELS[note.decision_tag as DecisionTag]}
            </span>
          </div>
          <span className="text-xs text-caption">
            {formatRelative(note.updated_at)}
          </span>
        </div>
        {note.content_md && (
          <p className="mt-2 text-sm text-ink/90 line-clamp-3 whitespace-pre-wrap">
            {note.content_md}
          </p>
        )}
      </Link>
    </li>
  )
}


function EmptyState({ activeTag }: { activeTag: DecisionTag | null }) {
  if (activeTag) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-surface p-6 text-center">
        <p className="text-sm text-ink">
          No notes tagged{" "}
          <span className="font-semibold">{TAG_LABELS[activeTag]}</span> yet.
        </p>
        <p className="mt-1 text-xs text-caption">
          Open any analysis page and use the &ldquo;My note&rdquo; panel to
          start.
        </p>
      </div>
    )
  }
  return (
    <div className="rounded-xl border border-dashed border-border bg-surface p-6 text-center">
      <p className="text-sm text-ink">You have not taken any notes yet.</p>
      <p className="mt-1 text-xs text-caption">
        Visit any analysis page and use the &ldquo;My note&rdquo; panel on the
        right side rail.
      </p>
      <Link
        href="/discover"
        className="mt-4 inline-block rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand/90"
      >
        Discover stocks
      </Link>
    </div>
  )
}


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
