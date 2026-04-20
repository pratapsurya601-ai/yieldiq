"use client"

import { useEffect, useState } from "react"
import { cn } from "@/lib/utils"
import {
  buildShareUrl,
  loadSavedQueries,
  saveSavedQueries,
  type SavedQuery,
} from "@/lib/screenerFilters"

interface SavedQueriesProps {
  // Bumped whenever the parent writes a new query to localStorage so we
  // know to re-read. Cheaper than a pub/sub and avoids the `storage` event
  // only firing in other tabs.
  reloadToken: number
  onLoad: (q: SavedQuery) => void
  pathname: string
}

export default function SavedQueries({ reloadToken, onLoad, pathname }: SavedQueriesProps) {
  const [queries, setQueries] = useState<SavedQuery[]>([])
  const [copiedId, setCopiedId] = useState<string | null>(null)

  useEffect(() => {
    setQueries(loadSavedQueries())
  }, [reloadToken])

  const remove = (id: string) => {
    const next = queries.filter((q) => q.id !== id)
    setQueries(next)
    saveSavedQueries(next)
  }

  const copyShare = async (q: SavedQuery) => {
    const url = buildShareUrl(pathname, q.filters, q.sort, q.limit)
    const full = typeof window !== "undefined" ? `${window.location.origin}${url}` : url
    try {
      await navigator.clipboard.writeText(full)
      setCopiedId(q.id)
      setTimeout(() => setCopiedId((c) => (c === q.id ? null : c)), 1500)
    } catch {
      // Clipboard denied — fall back to showing the URL inline.
      window.prompt("Copy share URL", full)
    }
  }

  if (queries.length === 0) {
    return (
      <div className="rounded-2xl border border-border bg-bg p-4">
        <h3 className="text-sm font-semibold text-ink mb-1">Saved queries</h3>
        <p className="text-xs text-caption">Saved queries appear here. Save one to reuse it later.</p>
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-border bg-white p-4">
      <h3 className="text-sm font-semibold text-ink mb-3">Saved queries</h3>
      <ul className="space-y-2">
        {queries.map((q) => (
          <li key={q.id} className="rounded-lg border border-border bg-bg p-3">
            <div className="flex items-start justify-between gap-2">
              <button
                type="button"
                onClick={() => onLoad(q)}
                className="text-left flex-1 min-w-0"
              >
                <div className="text-sm font-medium text-ink truncate">{q.name}</div>
                <div className="text-xs text-caption truncate">
                  {q.filters.length} filter{q.filters.length === 1 ? "" : "s"} {"\u00b7"} sort {q.sort || "default"}
                </div>
              </button>
              <div className="flex items-center gap-1 shrink-0">
                <button
                  type="button"
                  onClick={() => copyShare(q)}
                  className={cn(
                    "text-xs px-2 py-1 rounded border border-border",
                    "hover:bg-border transition-colors",
                    copiedId === q.id ? "text-green-700 border-green-200 bg-green-50" : "text-body"
                  )}
                >
                  {copiedId === q.id ? "Copied" : "Share"}
                </button>
                <button
                  type="button"
                  onClick={() => remove(q.id)}
                  aria-label="Delete saved query"
                  className="text-xs px-2 py-1 rounded border border-border text-caption hover:text-red-600 hover:border-red-200"
                >
                  {"\u00d7"}
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
