"use client"

import type { ReactNode, Ref } from "react"

/** Section card shell — the mockups' `.sec` + `.sh` header row. */
export function Section({
  id,
  num,
  title,
  ribbon,
  children,
  innerRef,
  highlight = false,
}: {
  id?: string
  num?: string
  title?: string
  ribbon?: ReactNode
  children: ReactNode
  innerRef?: Ref<HTMLElement>
  highlight?: boolean
}) {
  return (
    <section
      id={id}
      ref={innerRef}
      className={`mb-3.5 scroll-mt-24 rounded-2xl border bg-surface px-4 py-4 transition-[border-color,transform] duration-200 hover:-translate-y-px md:px-5 ${
        highlight ? "border-2 border-tone-info-bd" : "border-border hover:border-caption/50"
      }`}
    >
      {(num || title) && (
        <div className="mb-3.5 flex flex-wrap items-center justify-between gap-2.5">
          <div className="flex items-center gap-2.5">
            {num && (
              <span className="flex h-[26px] min-w-[26px] items-center justify-center rounded-full bg-tone-info-bg px-2 text-[12px] text-tone-info-fg">
                {num}
              </span>
            )}
            <span className="text-[16px] font-medium text-ink">{title}</span>
          </div>
          {ribbon}
        </div>
      )}
      {children}
    </section>
  )
}

/** Confidence / status ribbon — the mockups' `.rib`. */
export function Ribbon({
  tone,
  icon,
  children,
}: {
  tone: "good" | "warn" | "info"
  icon?: ReactNode
  children: ReactNode
}) {
  const cls =
    tone === "good"
      ? "bg-tone-good-bg text-tone-good-fg"
      : tone === "warn"
        ? "bg-tone-warn-bg text-tone-warn-fg"
        : "bg-tone-info-bg text-tone-info-fg"
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-[3px] text-[11px] ${cls}`}
    >
      {icon}
      {children}
    </span>
  )
}

/** Small metric tile — the mockups' `.kpi`. */
export function Kpi({
  label,
  value,
  sub,
  valueClass = "text-ink",
  className = "",
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  valueClass?: string
  className?: string
}) {
  return (
    <div className={`rounded-lg border border-border/60 bg-raised px-3 py-2.5 ${className}`}>
      <div className="text-[11.5px] text-caption">{label}</div>
      <div className={`num mt-px text-[18px] font-medium ${valueClass}`}>
        {value}
        {sub && <small className="ml-1 text-[11px] font-normal">{sub}</small>}
      </div>
    </div>
  )
}

/** Sub-heading inside a section — the mockups' `.subh`. */
export function Subh({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mb-2.5 mt-0.5 text-[13px] font-medium text-ink ${className}`}>{children}</div>
}

/** Muted body copy — the mockups' `.muted`. */
export function Muted({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`text-[12.5px] leading-relaxed text-caption ${className}`}>{children}</div>
}

/** Numbered step bullet for §5 — the mockups' `.stepn`. */
export function StepNum({ n }: { n: number }) {
  return (
    <span className="mr-1.5 inline-flex h-[18px] w-[18px] items-center justify-center rounded-full bg-tone-info-bg align-[-3px] text-[11px] text-tone-info-fg">
      {n}
    </span>
  )
}

/** Legend row — the mockups' `.leg`. */
export function Legend({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`mt-2 flex flex-wrap items-center gap-3.5 text-[12px] text-caption ${className}`}>
      {children}
    </div>
  )
}

export function Swatch({ color }: { color: string }) {
  return (
    <span
      className="inline-block h-[9px] w-[9px] rounded-[2px]"
      style={{ background: color }}
      aria-hidden="true"
    />
  )
}

/** Two-column responsive grid — the mockups' `.two`. */
export function TwoCol({
  children,
  align = "center",
  className = "",
}: {
  children: ReactNode
  align?: "center" | "start" | "stretch"
  className?: string
}) {
  const alignCls = align === "start" ? "items-start" : align === "stretch" ? "items-stretch" : "items-center"
  return (
    <div className={`grid grid-cols-1 gap-4 md:grid-cols-2 ${alignCls} ${className}`}>{children}</div>
  )
}

/** Demo action button (all actions are no-ops in this preview). */
export function DemoButton({
  children,
  accent = false,
  className = "",
  onClick,
}: {
  children: ReactNode
  accent?: boolean
  className?: string
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12.5px] transition-colors ${
        accent
          ? "border-tone-info-bd text-tone-info-fg hover:bg-tone-info-bg"
          : "border-border bg-surface text-body hover:bg-raised"
      } ${className}`}
    >
      {children}
    </button>
  )
}
