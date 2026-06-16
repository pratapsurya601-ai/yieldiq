/**
 * TabEmptyState — the honest "this data isn't here yet" panel.
 *
 * Server-renderable (no hooks). Used by the Portfolio / Risk / Peers
 * tabs whenever their backend block is absent or still updating. It is
 * NOT a fake placeholder — it states plainly that the section is
 * refreshing / computing, so the page reads as truthful rather than
 * broken while the parallel backend PR lands.
 */
import type { ReactNode } from "react"

export default function TabEmptyState({
  title,
  message,
}: {
  title: string
  message: ReactNode
}) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-raised/60 p-8 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="mx-auto mt-1.5 max-w-md text-sm text-caption">{message}</p>
    </div>
  )
}
