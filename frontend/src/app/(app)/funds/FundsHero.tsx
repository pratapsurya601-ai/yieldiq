"use client"
/**
 * FundsHero — editorial hero band for the /funds browse hub.
 *
 * An editorial display headline (font-editorial + one gradient-accent
 * span) over a short descriptive subhead, followed by a 3-tile stat
 * strip with animated counters (NumberFlip) for the three identity
 * aggregates that fill at scale: total schemes tracked, distinct
 * categories, and fund houses (AMCs).
 *
 * Every number is backed by the categories census (true COUNT(*) per
 * category from /api/v1/funds/categories) — never a per-page sample —
 * so the figures are honest and never null. NumberFlip renders the
 * final value on the server (SSR) so there is no count-from-zero flash
 * and zero CLS; reduced-motion users see the plain value.
 *
 * SEBI: descriptive only. No advisory vocab; figures are facts.
 */
import { NumberFlip, Reveal } from "@/components/motion"

function HeroTile({
  value,
  label,
  sublabel,
  duration,
}: {
  value: number
  label: string
  sublabel?: string
  duration: number
}) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-4">
      <div className="text-2xl font-semibold leading-tight text-ink num sm:text-3xl">
        <NumberFlip value={value} duration={duration} />
      </div>
      <div className="mt-1 text-[10px] font-bold uppercase tracking-wider text-caption">
        {label}
      </div>
      {sublabel ? (
        <div className="text-[10px] leading-3 text-caption">{sublabel}</div>
      ) : null}
    </div>
  )
}

export default function FundsHero({
  total,
  categoryCount,
  largestCategoryCount,
  largestCategoryLabel,
  children,
}: {
  total: number
  categoryCount: number
  /** Scheme count in the single largest category (census-backed). */
  largestCategoryCount: number
  /** Compact label of that largest category, e.g. "Index Funds". */
  largestCategoryLabel: string
  /** Search box is composed in by the server page so this stays a
   *  pure presentational hero (the input is its own client island). */
  children?: React.ReactNode
}) {
  return (
    <Reveal direction="up" as="section" className="space-y-5">
      <div className="space-y-3">
        <p className="text-[11px] font-semibold uppercase leading-4 tracking-[0.06em] text-caption">
          Mutual Fund Research
        </p>
        <h1 className="font-editorial text-display-xl text-ink">
          Explore Indian mutual funds, by{" "}
          <span className="text-display-accent">category, AMC and risk.</span>
        </h1>
        <p className="max-w-2xl text-[15px] leading-[22px] text-body">
          Read-only NAV history, benchmark-relative returns, and AMC-published
          risk labels for Indian mutual-fund schemes. Browse the universe by
          category, fund house, or riskometer band — descriptive data only.
        </p>
      </div>

      {children}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <HeroTile value={total} label="Schemes tracked" duration={1.4} />
        <HeroTile value={categoryCount} label="Categories" duration={1.0} />
        {largestCategoryCount > 0 ? (
          <HeroTile
            value={largestCategoryCount}
            label="Largest category"
            sublabel={largestCategoryLabel}
            duration={1.0}
          />
        ) : (
          <HeroTile value={total} label="Schemes tracked" duration={1.0} />
        )}
      </div>
    </Reveal>
  )
}
