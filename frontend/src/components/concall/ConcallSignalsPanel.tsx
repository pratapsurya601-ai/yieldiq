"use client"

// ConcallSignalsPanel — Phase G-intel-phase1 (c).
//
// Renders the STRUCTURED signals extracted from an earnings-call
// transcript by the Anthropic-backed concall_intel_service (Phase 1).
// Distinct from the sibling ConcallsPanel, which lists free-text
// Groq-summarised transcripts. This panel is meant to render ABOVE
// the ConcallsPanel on /analysis/[ticker] so the structured guidance,
// capex commitments, margin commentary, tone, and key quotes appear
// first — they're the higher-signal artefact.
//
// Data source: GET /api/v1/concall/signals/by-ticker/{ticker}/latest
// (also see GET /api/v1/concall/{transcript_id}/signals for the
// per-transcript lookup used by the operator review surface).
//
// SEBI discipline: when the backend marks a row with
// quality_flag='sebi_withheld', the response collapses to
// {signals: null, withheld: true}. The panel renders a neutral
// "Withheld pending review" placeholder rather than any free text in
// that case. When signals are simply absent (no extraction yet for
// the ticker), the panel renders nothing — the page already has the
// ConcallsPanel empty state below.

import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"

interface GuidanceChange {
  metric?: string
  previous?: string
  new?: string
  direction?: string
  quote?: string
}

interface CapexCommitment {
  amount_cr?: number | string
  horizon?: string
  purpose?: string
  quote?: string
}

interface MarginCommentary {
  segment?: string
  direction?: string
  drivers?: string[]
  quote?: string
}

interface KeyQuote {
  speaker?: string
  topic?: string
  quote?: string
}

export interface ConcallSignals {
  fiscal_period?: string | null
  concall_date?: string | null
  transcript_source?: string | null
  guidance_changes?: GuidanceChange[]
  capex_commitments?: CapexCommitment[]
  margin_commentary?: MarginCommentary[]
  management_tone?: "bullish" | "neutral" | "cautious" | "defensive" | string | null
  key_quotes?: KeyQuote[]
  extractor_version?: string | null
}

export interface ConcallSignalsResponse {
  signals: ConcallSignals | null
  withheld?: boolean
  ticker?: string | null
  fiscal_period?: string | null
  transcript_id?: number | null
  quality_flag?: string | null
  generated_at?: string | null
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

async function fetchSignals(ticker: string): Promise<ConcallSignalsResponse | null> {
  const t = (ticker || "").trim().toUpperCase()
  if (!t) return null
  const res = await fetch(
    `${API_BASE}/api/v1/concall/signals/by-ticker/${encodeURIComponent(t)}/latest`,
  )
  if (!res.ok) return null
  return res.json()
}

function toneClass(tone: string | null | undefined): string {
  switch ((tone || "").toLowerCase()) {
    case "bullish":
      return "bg-emerald-500/10 text-tone-good-fg dark:text-emerald-300"
    case "cautious":
      return "bg-amber-500/10 text-tone-warn-fg dark:text-amber-300"
    case "defensive":
      return "bg-rose-500/10 text-rose-700 dark:text-rose-300"
    case "neutral":
    default:
      return "bg-surface text-caption"
  }
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return ""
  try {
    const d = new Date(iso)
    if (!isFinite(d.getTime())) return ""
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
  } catch {
    return ""
  }
}

interface PanelProps {
  ticker: string
  // Optional injected data for tests/storybook. When provided the
  // component skips the network fetch and renders directly.
  initialData?: ConcallSignalsResponse | null
}

export default function ConcallSignalsPanel({ ticker, initialData }: PanelProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["concall-signals", ticker],
    queryFn: () => fetchSignals(ticker),
    enabled: !!ticker && initialData === undefined,
    staleTime: 60 * 60 * 1000,
    retry: 1,
    initialData: initialData === undefined ? undefined : initialData,
  })

  const payload = data ?? initialData ?? null

  // 1. Withheld branch — show a neutral placeholder, no free text.
  if (payload && payload.withheld) {
    return (
      <div
        className="bg-bg rounded-2xl border border-border p-4"
        data-testid="concall-signals-withheld"
      >
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-ink">Concall Signals</h2>
          <span className="text-[10px] uppercase tracking-wide text-caption">
            quality review
          </span>
        </div>
        <p className="text-xs italic text-caption">
          Withheld pending review. The most recent extraction tripped the
          SEBI vocabulary check and is queued for operator re-review.
        </p>
      </div>
    )
  }

  // 2. No signals + no withheld flag → render nothing. The sibling
  //    ConcallsPanel renders an empty-state below us already.
  const signals = payload?.signals ?? null
  if (!signals && !isLoading) {
    return null
  }

  if (isLoading || !signals) {
    return (
      <div className="bg-bg rounded-2xl border border-border p-4">
        <div className="h-4 w-32 bg-surface rounded animate-pulse mb-4" />
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-12 bg-surface rounded animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  const guidance = signals.guidance_changes ?? []
  const capex = signals.capex_commitments ?? []
  const margin = signals.margin_commentary ?? []
  const quotes = signals.key_quotes ?? []
  const tone = signals.management_tone ?? "neutral"
  const headerDate = useMemo(() => formatDate(signals.concall_date), [signals.concall_date])

  return (
    <div
      className="bg-bg rounded-2xl border border-border p-4"
      data-testid="concall-signals-panel"
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">Concall Signals</h2>
          <p className="text-[11px] text-caption mt-0.5">
            Structured extraction from the latest earnings call —
            guidance, capex, margins, tone, and key quotes.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {signals.fiscal_period && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide bg-accent/10 text-accent">
              {signals.fiscal_period}
            </span>
          )}
          {headerDate && (
            <span className="text-[11px] text-caption">{headerDate}</span>
          )}
        </div>
      </div>

      {/* Section 1: Management tone */}
      <section className="mb-4" data-testid="signals-section-tone">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-caption mb-1.5">
          Management tone
        </h3>
        <span
          className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${toneClass(
            tone,
          )}`}
        >
          {String(tone || "neutral")}
        </span>
      </section>

      {/* Section 2: Guidance changes */}
      <section className="mb-4" data-testid="signals-section-guidance">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-caption mb-1.5">
          Guidance changes
        </h3>
        {guidance.length === 0 ? (
          <p className="text-xs italic text-caption">
            No fresh guidance disclosed on this call.
          </p>
        ) : (
          <ul className="space-y-2">
            {guidance.slice(0, 6).map((g, i) => (
              <li
                key={i}
                className="border border-border rounded-lg p-3 bg-surface/40"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-ink">
                    {g.metric || "metric"}
                  </span>
                  {g.direction && (
                    <span className="text-[10px] uppercase tracking-wide text-caption">
                      {g.direction}
                    </span>
                  )}
                </div>
                {(g.previous || g.new) && (
                  <p className="text-[11px] text-caption">
                    {g.previous ?? "—"} → {g.new ?? "—"}
                  </p>
                )}
                {g.quote && (
                  <p className="mt-1 text-xs italic text-ink leading-relaxed">
                    &ldquo;{g.quote}&rdquo;
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Section 3: Capex commitments */}
      <section className="mb-4" data-testid="signals-section-capex">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-caption mb-1.5">
          Capex commitments
        </h3>
        {capex.length === 0 ? (
          <p className="text-xs italic text-caption">
            No new capex commitments disclosed.
          </p>
        ) : (
          <ul className="space-y-2">
            {capex.slice(0, 6).map((c, i) => (
              <li
                key={i}
                className="border border-border rounded-lg p-3 bg-surface/40"
              >
                <div className="flex items-center gap-2 mb-1">
                  {c.amount_cr !== undefined && (
                    <span className="text-xs font-medium text-ink">
                      Rs {c.amount_cr} Cr
                    </span>
                  )}
                  {c.horizon && (
                    <span className="text-[10px] uppercase tracking-wide text-caption">
                      {c.horizon}
                    </span>
                  )}
                </div>
                {c.purpose && (
                  <p className="text-[11px] text-caption">{c.purpose}</p>
                )}
                {c.quote && (
                  <p className="mt-1 text-xs italic text-ink leading-relaxed">
                    &ldquo;{c.quote}&rdquo;
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Section 4: Margin commentary */}
      <section className="mb-4" data-testid="signals-section-margin">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-caption mb-1.5">
          Margin commentary
        </h3>
        {margin.length === 0 ? (
          <p className="text-xs italic text-caption">
            No segment-level margin commentary captured.
          </p>
        ) : (
          <ul className="space-y-2">
            {margin.slice(0, 6).map((m, i) => (
              <li
                key={i}
                className="border border-border rounded-lg p-3 bg-surface/40"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-ink">
                    {m.segment || "segment"}
                  </span>
                  {m.direction && (
                    <span className="text-[10px] uppercase tracking-wide text-caption">
                      {m.direction}
                    </span>
                  )}
                </div>
                {m.drivers && m.drivers.length > 0 && (
                  <p className="text-[11px] text-caption">
                    Drivers: {m.drivers.join(", ")}
                  </p>
                )}
                {m.quote && (
                  <p className="mt-1 text-xs italic text-ink leading-relaxed">
                    &ldquo;{m.quote}&rdquo;
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Section 5: Key quotes */}
      <section data-testid="signals-section-quotes">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-caption mb-1.5">
          Key quotes
        </h3>
        {quotes.length === 0 ? (
          <p className="text-xs italic text-caption">No key quotes captured.</p>
        ) : (
          <ul className="space-y-2">
            {quotes.slice(0, 6).map((q, i) => (
              <li
                key={i}
                className="border-l-2 border-accent/60 pl-3 py-1"
              >
                {(q.speaker || q.topic) && (
                  <p className="text-[10px] uppercase tracking-wide text-caption mb-0.5">
                    {[q.speaker, q.topic].filter(Boolean).join(" · ")}
                  </p>
                )}
                {q.quote && (
                  <p className="text-xs italic text-ink leading-relaxed">
                    &ldquo;{q.quote}&rdquo;
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="mt-4 text-[10px] text-caption leading-relaxed">
        Signals are AI-extracted from management commentary. They
        describe what management said and are not investment advice.
      </p>
    </div>
  )
}
