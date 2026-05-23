"use client"

// ARSignalsPanel — Phase H-frontend (Block II).
//
// Renders the STRUCTURED signals extracted from an annual report
// PDF by the Anthropic-backed ar_intel_service (Phase H). Sibling
// to ConcallSignalsPanel; renders ABOVE the existing
// AnnualReportsPanel on /analysis/[ticker] so the rich structured
// view (segments, capex, RPT, auditor flags, contingent
// liabilities, management outlook) renders first.
//
// Data source: GET /api/v1/annual-reports/signals/by-ticker/{ticker}/latest
// (per-AR drilldown via GET /api/v1/annual-reports/{ar_id}/signals).
//
// Quality discipline: when the backend marks the row
// quality_flag='withheld', the response collapses to
// {signals: null, withheld: true}. The panel renders a neutral
// "Withheld pending review" placeholder rather than any free
// text from the LLM. When signals are simply absent (no
// extraction yet for the ticker), the panel renders nothing —
// the page already has the AnnualReportsPanel below.
//
// Field shape: the backend stores signals as the LLM extracted
// them. The canonical keys (verified against ar_signals rows
// loaded via load_manual_ar_signals.py) are:
//   segment_data        -> name, revenue_cr, ebit_cr, yoy_growth_pct, note
//   capex_commitments   -> timeline, amount_cr, description
//   related_party_*     -> party, nature, amount_cr
//   auditor_flags       -> type, summary
//   contingent_*        -> amount_cr, description
// We accept legacy aliases (segment/counterparty/project/fy/...) as
// fall-throughs so a future loader that renames keys does not
// regress the panel.

import { useQuery } from "@tanstack/react-query"

interface SegmentRow {
  name?: string
  segment?: string
  revenue_cr?: number | string | null
  ebit_cr?: number | string | null
  yoy_growth_pct?: number | string | null
  note?: string | null
  fy?: string | null
  quote?: string | null
}

interface CapexRow {
  amount_cr?: number | string | null
  timeline?: string | null
  description?: string | null
  fy?: string | null
  project?: string | null
  quote?: string | null
}

interface RPTRow {
  party?: string | null
  counterparty?: string | null
  relationship?: string | null
  nature?: string | null
  amount_cr?: number | string | null
  fy?: string | null
  quote?: string | null
}

interface AuditorFlagRow {
  type?: string | null
  summary?: string | null
  description?: string | null
  as_of?: string | null
}

interface ContingentLiabilityRow {
  description?: string | null
  amount_cr?: number | string | null
  as_of?: string | null
}

export interface ARSignals {
  segment_data?: SegmentRow[]
  capex_commitments?: CapexRow[]
  related_party_transactions?: RPTRow[]
  auditor_flags?: AuditorFlagRow[]
  contingent_liabilities?: ContingentLiabilityRow[]
  management_outlook?: string | null
  model_version?: string | null
  prompt_version?: number | null
}

export interface ARSignalsResponse {
  signals: ARSignals | null
  withheld?: boolean
  ticker?: string | null
  fiscal_year?: number | null
  annual_report_id?: number | null
  quality_flag?: string | null
  generated_at?: string | null
  ar_url?: string | null
  published_at?: string | null
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

async function fetchSignals(ticker: string): Promise<ARSignalsResponse | null> {
  const t = (ticker || "").trim().toUpperCase()
  if (!t) return null
  const res = await fetch(
    `${API_BASE}/api/v1/annual-reports/signals/by-ticker/${encodeURIComponent(t)}/latest`,
  )
  if (!res.ok) return null
  return res.json()
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return ""
  try {
    const d = new Date(iso)
    if (!isFinite(d.getTime())) return ""
    return d.toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    })
  } catch {
    return ""
  }
}

function formatCr(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—"
  const n = typeof v === "string" ? Number(v) : v
  if (!isFinite(n as number)) return String(v)
  return `Rs ${(n as number).toLocaleString("en-IN", { maximumFractionDigits: 2 })} Cr`
}

function formatPct(v: number | string | null | undefined): string | null {
  if (v === null || v === undefined || v === "") return null
  const n = typeof v === "string" ? Number(v) : v
  if (!isFinite(n as number)) return null
  const sign = (n as number) > 0 ? "+" : ""
  return `${sign}${(n as number).toFixed(1)}% YoY`
}

interface PanelProps {
  ticker: string
  // Optional injected data for tests / storybook. When provided
  // the component skips the network fetch and renders directly.
  initialData?: ARSignalsResponse | null
}

export default function ARSignalsPanel({ ticker, initialData }: PanelProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["ar-signals", ticker],
    queryFn: () => fetchSignals(ticker),
    enabled: !!ticker && initialData === undefined,
    staleTime: 6 * 60 * 60 * 1000, // 6 h — ARs are slow-moving
    retry: 1,
    initialData: initialData === undefined ? undefined : initialData,
  })

  const payload = data ?? initialData ?? null

  // 1. Withheld branch — neutral placeholder, no free text.
  if (payload && payload.withheld) {
    return (
      <div
        className="bg-bg rounded-2xl border border-border p-5"
        data-testid="ar-signals-withheld"
      >
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-ink">
            Annual Report Signals
          </h2>
          <span className="text-[10px] uppercase tracking-wide text-caption">
            quality review
          </span>
        </div>
        <p className="text-xs italic text-caption">
          Withheld pending review. The most recent extraction tripped the
          quality vocabulary check and is queued for operator re-review.
        </p>
      </div>
    )
  }

  // 2. No signals + no withheld flag → render nothing. The sibling
  //    AnnualReportsPanel renders the AR link list below us.
  const signals = payload?.signals ?? null
  if (!signals && !isLoading) {
    return null
  }

  if (isLoading || !signals) {
    return (
      <div className="bg-bg rounded-2xl border border-border p-5">
        <div className="h-4 w-32 bg-surface rounded animate-pulse mb-4" />
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-12 bg-surface rounded animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  const segments = signals.segment_data ?? []
  const capex = signals.capex_commitments ?? []
  const rpts = signals.related_party_transactions ?? []
  const auditors = signals.auditor_flags ?? []
  const liabilities = signals.contingent_liabilities ?? []
  const outlook = (signals.management_outlook ?? "").trim()
  const fy = payload?.fiscal_year
  const published = formatDate(payload?.published_at ?? payload?.generated_at)

  return (
    <div
      className="bg-bg rounded-2xl border border-border p-5"
      data-testid="ar-signals-panel"
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">
            Annual Report Signals
          </h2>
          <p className="text-[11px] text-caption mt-0.5">
            Structured extraction from the latest annual report —
            segments, capex commitments, related-party transactions,
            auditor flags, contingent liabilities, and outlook.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {fy && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide bg-accent/10 text-accent">
              FY{String(fy).slice(-2)}
            </span>
          )}
          {published && (
            <span className="text-[11px] text-caption">{published}</span>
          )}
        </div>
      </div>

      {/* Section 1: Segment data */}
      <section className="mb-4" data-testid="ar-section-segments">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-caption mb-1.5">
          Segment data
        </h3>
        {segments.length === 0 ? (
          <p className="text-xs italic text-caption">
            No segment breakdown disclosed in this AR.
          </p>
        ) : (
          <ul className="space-y-2">
            {segments.slice(0, 8).map((s, i) => {
              const label = s.name || s.segment || "segment"
              const yoy = formatPct(s.yoy_growth_pct)
              return (
                <li
                  key={i}
                  className="border border-border rounded-lg p-3 bg-surface/40"
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-xs font-medium text-ink">
                      {label}
                    </span>
                    {(s.fy || yoy) && (
                      <span className="text-[10px] uppercase tracking-wide text-caption">
                        {s.fy || yoy}
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-caption">
                    Revenue {formatCr(s.revenue_cr)}
                    {" · "}
                    EBIT {formatCr(s.ebit_cr)}
                  </p>
                  {s.note && (
                    <p className="mt-1 text-[11px] text-caption">{s.note}</p>
                  )}
                  {s.quote && (
                    <p className="mt-1 text-xs italic text-ink leading-relaxed">
                      &ldquo;{s.quote}&rdquo;
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {/* Section 2: Capex commitments */}
      <section className="mb-4" data-testid="ar-section-capex">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-caption mb-1.5">
          Capex commitments
        </h3>
        {capex.length === 0 ? (
          <p className="text-xs italic text-caption">
            No capex commitments disclosed.
          </p>
        ) : (
          <ul className="space-y-2">
            {capex.slice(0, 6).map((c, i) => {
              const when = c.timeline || c.fy
              const detail = c.description || c.project
              return (
                <li
                  key={i}
                  className="border border-border rounded-lg p-3 bg-surface/40"
                >
                  <div className="flex items-center gap-2 mb-1">
                    {c.amount_cr !== undefined && c.amount_cr !== null && (
                      <span className="text-xs font-medium text-ink">
                        {formatCr(c.amount_cr)}
                      </span>
                    )}
                    {when && (
                      <span className="text-[10px] uppercase tracking-wide text-caption">
                        {when}
                      </span>
                    )}
                  </div>
                  {detail && (
                    <p className="text-[11px] text-caption">{detail}</p>
                  )}
                  {c.quote && (
                    <p className="mt-1 text-xs italic text-ink leading-relaxed">
                      &ldquo;{c.quote}&rdquo;
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {/* Section 3: Related-party transactions */}
      <section className="mb-4" data-testid="ar-section-rpt">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-caption mb-1.5">
          Related-party transactions
        </h3>
        {rpts.length === 0 ? (
          <p className="text-xs italic text-caption">
            No material RPTs disclosed.
          </p>
        ) : (
          <ul className="space-y-2">
            {rpts.slice(0, 6).map((r, i) => {
              const who = r.party || r.counterparty || "counterparty"
              return (
                <li
                  key={i}
                  className="border border-border rounded-lg p-3 bg-surface/40"
                >
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span className="text-xs font-medium text-ink">
                      {who}
                    </span>
                    {r.relationship && (
                      <span className="text-[10px] uppercase tracking-wide text-caption">
                        {r.relationship}
                      </span>
                    )}
                  </div>
                  {r.nature && (
                    <p className="text-[11px] text-caption">{r.nature}</p>
                  )}
                  <p className="text-[11px] text-caption">
                    {formatCr(r.amount_cr)}
                    {r.fy ? ` · ${r.fy}` : ""}
                  </p>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {/* Section 4: Auditor flags */}
      <section className="mb-4" data-testid="ar-section-auditor">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-caption mb-1.5">
          Auditor flags
        </h3>
        {auditors.length === 0 ? (
          <p className="text-xs italic text-caption">
            No auditor flags raised.
          </p>
        ) : (
          <ul className="space-y-2">
            {auditors.slice(0, 6).map((a, i) => {
              const body = a.summary || a.description
              return (
                <li
                  key={i}
                  className="border border-border rounded-lg p-3 bg-surface/40"
                >
                  <div className="flex items-center gap-2 mb-1">
                    {a.type && (
                      <span className="text-xs font-medium text-ink">
                        {a.type}
                      </span>
                    )}
                    {a.as_of && (
                      <span className="text-[10px] uppercase tracking-wide text-caption">
                        {a.as_of}
                      </span>
                    )}
                  </div>
                  {body && (
                    <p className="text-[11px] text-caption">{body}</p>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {/* Section 5: Contingent liabilities */}
      <section className="mb-4" data-testid="ar-section-liabilities">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-caption mb-1.5">
          Contingent liabilities
        </h3>
        {liabilities.length === 0 ? (
          <p className="text-xs italic text-caption">
            No material contingent liabilities disclosed.
          </p>
        ) : (
          <ul className="space-y-2">
            {liabilities.slice(0, 6).map((l, i) => (
              <li
                key={i}
                className="border border-border rounded-lg p-3 bg-surface/40"
              >
                <div className="flex items-center gap-2 mb-1">
                  {l.amount_cr !== undefined && l.amount_cr !== null && (
                    <span className="text-xs font-medium text-ink">
                      {formatCr(l.amount_cr)}
                    </span>
                  )}
                  {l.as_of && (
                    <span className="text-[10px] uppercase tracking-wide text-caption">
                      {l.as_of}
                    </span>
                  )}
                </div>
                {l.description && (
                  <p className="text-[11px] text-caption">{l.description}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Section 6: Management outlook */}
      <section data-testid="ar-section-outlook">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-caption mb-1.5">
          Management outlook
        </h3>
        {!outlook ? (
          <p className="text-xs italic text-caption">
            No MD&amp;A narrative captured.
          </p>
        ) : (
          <p className="text-xs italic text-ink leading-relaxed">
            &ldquo;{outlook}&rdquo;
          </p>
        )}
      </section>

      <p className="mt-4 text-[10px] text-caption leading-relaxed">
        Signals are AI-extracted from the annual report. They describe
        what the AR disclosed and are not investment advice.
      </p>
    </div>
  )
}
