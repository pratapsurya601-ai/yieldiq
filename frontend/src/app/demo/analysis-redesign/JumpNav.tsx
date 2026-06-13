"use client"

// B · Sticky jump-rail — the demoted tabs. Random access without
// breaking the single-scroll narrative.
import { useReducedMotion } from "@/components/anim"

const ITEMS: [string, string][] = [
  ["sec-1", "Answer"],
  ["sec-2", "Thesis"],
  ["sec-3", "Business"],
  ["sec-4", "Financials"],
  ["sec-5", "Valuation"],
  ["sec-6", "Risk"],
  ["sec-7", "Ownership"],
  ["sec-8", "Peers"],
  ["sec-9", "News"],
]

export default function JumpNav() {
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
      {ITEMS.map(([id, label]) => (
        <button
          key={id}
          type="button"
          onClick={() => jump(id)}
          className="rounded-full border border-border/70 bg-surface px-2.5 py-[5px] text-[12px] font-medium text-caption transition-colors hover:border-tone-info-bd hover:bg-tone-info-bg hover:text-tone-info-fg"
        >
          {label}
        </button>
      ))}
    </nav>
  )
}
