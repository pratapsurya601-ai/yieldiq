"use client"

// v2 · Sticky jump-rail — the demoted tabs. Random access without
// breaking the single-scroll narrative.
//
// PORTED from app/demo/analysis-redesign/JumpNav.tsx. The mock fixed
// ITEMS list is replaced by an `items` prop so the body only renders
// anchors for sections that actually exist in v2 so far (spine + stubs).
import { useReducedMotion } from "@/components/anim"

export interface JumpNavItem {
  /** Anchor id (matches a section's `id`). */
  id: string
  /** Pill label. */
  label: string
}

export default function JumpNavV2({ items }: { items: JumpNavItem[] }) {
  const reduced = useReducedMotion()

  const jump = (id: string) => {
    document.getElementById(id)?.scrollIntoView({
      behavior: reduced ? "auto" : "smooth",
      block: "start",
    })
  }

  return (
    <nav
      aria-label="Jump to section"
      className="sticky top-2 z-40 mb-3.5 flex flex-wrap gap-1.5 rounded-xl border border-border/60 bg-raised/90 p-2 shadow-[0_4px_14px_-4px_rgba(15,23,42,0.14)] backdrop-blur"
    >
      {items.map((it) => (
        <button
          key={it.id}
          type="button"
          onClick={() => jump(it.id)}
          className="rounded-full border border-border/70 bg-surface px-2.5 py-[5px] text-[12px] font-medium text-caption transition-colors hover:border-tone-info-bd hover:bg-tone-info-bg hover:text-tone-info-fg"
        >
          {it.label}
        </button>
      ))}
    </nav>
  )
}
