"use client"

// ARSignalsPanel — Phase H-frontend (Block II) + extended fields
// (PR #613).
//
// Renders the STRUCTURED signals extracted from an annual report
// PDF by the Anthropic-backed ar_intel_service. Sibling to
// ConcallSignalsPanel; renders ABOVE the existing AnnualReportsPanel
// on /analysis/[ticker].
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
// Sub-panels (in order):
//   1.  Segment data            (default: expanded)
//   2.  Capex commitments
//   3.  Related-party transactions
//   4.  Auditor flags
//   5.  Contingent liabilities
//   6.  Management outlook
//   7.  Risk factors            (PR #613)
//   8.  ESG metrics             (PR #613)
//   9.  Governance signals      (PR #613)
//   10. Workforce metrics       (PR #613)
//   11. Customer concentration  (PR #613)
//   12. Operational KPIs        (PR #613)
//   13. Subsidiary summary      (PR #613)
//   14. Dividend history        (PR #613)
//   15. Capital actions         (PR #613)
//   16. Strategic priorities    (PR #613)
//
// Each PR #613 sub-panel renders ONLY when its corresponding JSONB
// column is present and non-empty. The 21 already-loaded AR rows
// have these as null/missing, so the panel degrades cleanly. The
// 887-AR wave (in flight) will populate them.

import { useState } from "react"
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

// ---- PR #613 extended-field shapes -------------------------------

interface RiskFactorRow {
  category?: string | null
  description?: string | null
  mitigation?: string | null
}

interface ESGMetrics {
  scope1_emissions_tco2e?: number | string | null
  scope2_emissions_tco2e?: number | string | null
  scope3_emissions_tco2e?: number | string | null
  water_withdrawal_kl?: number | string | null
  renewable_energy_pct?: number | string | null
  gender_ratio_pct_female_workforce?: number | string | null
  lost_time_injury_frequency_rate?: number | string | null
  csr_spend_cr?: number | string | null
  note?: string | null
}

interface Governance {
  promoter_pledge_pct?: number | string | null
  promoter_shareholding_pct?: number | string | null
  board_independence_pct?: number | string | null
  auditor_remuneration_cr?: number | string | null
  whistleblower_complaints_count?: number | string | null
  sexual_harassment_complaints_count?: number | string | null
  regulatory_penalties_cr?: number | string | null
  note?: string | null
}

interface WorkforceMetrics {
  total_headcount?: number | string | null
  attrition_pct?: number | string | null
  gender_ratio_pct_female?: number | string | null
  training_hours_per_employee?: number | string | null
  employee_cost_pct_revenue?: number | string | null
  note?: string | null
}

interface SplitRow {
  region?: string | null
  channel?: string | null
  pct_revenue?: number | string | null
}

interface CustomerConcentration {
  top_10_customer_pct_revenue?: number | string | null
  geographic_split?: SplitRow[] | null
  channel_split?: SplitRow[] | null
  note?: string | null
}

interface OperationalKPIs {
  industry?: string | null
  metrics?: Record<string, number | string | null | undefined> | null
  note?: string | null
}

interface SubsidiaryRow {
  name?: string | null
  country?: string | null
  revenue_cr?: number | string | null
  pat_cr?: number | string | null
  networth_cr?: number | string | null
  ownership_pct?: number | string | null
}

interface DividendRow {
  fiscal_year?: number | string | null
  interim_dps_rs?: number | string | null
  final_dps_rs?: number | string | null
  special_dps_rs?: number | string | null
  total_dps_rs?: number | string | null
  payout_ratio_pct?: number | string | null
}

interface CapitalActionRow {
  type?: string | null
  date?: string | null
  ratio_or_price?: string | number | null
  amount_cr?: number | string | null
}

interface StrategicPriorityRow {
  priority?: string | null
  target?: string | null
  timeline?: string | null
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
  // PR #613 extended fields — all nullable / may be missing.
  risk_factors?: RiskFactorRow[] | null
  esg_metrics?: ESGMetrics | null
  governance?: Governance | null
  workforce_metrics?: WorkforceMetrics | null
  customer_concentration?: CustomerConcentration | null
  operational_kpis?: OperationalKPIs | null
  subsidiary_summary?: SubsidiaryRow[] | null
  dividend_history?: DividendRow[] | null
  capital_actions?: CapitalActionRow[] | null
  strategic_priorities?: StrategicPriorityRow[] | null
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

// Plain percentage formatter (no sign, no "YoY") for KPI tiles where
// the value is a level, not a growth rate.
function formatPctLevel(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—"
  const n = typeof v === "string" ? Number(v) : v
  if (!isFinite(n as number)) return String(v)
  return `${(n as number).toFixed(1)}%`
}

function formatNumber(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—"
  const n = typeof v === "string" ? Number(v) : v
  if (!isFinite(n as number)) return String(v)
  return (n as number).toLocaleString("en-IN", { maximumFractionDigits: 2 })
}

function isFilled(v: unknown): boolean {
  return v !== null && v !== undefined && v !== ""
}

function hasAnyFilled(obj: Record<string, unknown> | null | undefined): boolean {
  if (!obj) return false
  return Object.values(obj).some((v) => {
    if (v === null || v === undefined || v === "") return false
    if (Array.isArray(v)) return v.length > 0
    return true
  })
}

interface PanelProps {
  ticker: string
  // Optional injected data for tests / storybook. When provided
  // the component skips the network fetch and renders directly.
  initialData?: ARSignalsResponse | null
}

// Collapsible section wrapper. Header is clickable; body is hidden
// unless `open`. We use a controlled <details>-style pattern with
// useState so the header swap is testable and accessible.
interface CollapsibleProps {
  id: string
  title: string
  defaultOpen?: boolean
  testId: string
  children: React.ReactNode
}

function Collapsible({
  id,
  title,
  defaultOpen = false,
  testId,
  children,
}: CollapsibleProps) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="mb-4" data-testid={testId}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={`${id}-body`}
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between text-left mb-1.5 hover:opacity-80"
      >
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-caption">
          {title}
        </h3>
        <span className="text-[10px] text-caption" aria-hidden="true">
          {open ? "−" : "+"}
        </span>
      </button>
      {open && <div id={`${id}-body`}>{children}</div>}
    </section>
  )
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
        className="bg-bg rounded-2xl border border-border p-4"
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

  const segments = signals.segment_data ?? []
  const capex = signals.capex_commitments ?? []
  const rpts = signals.related_party_transactions ?? []
  const auditors = signals.auditor_flags ?? []
  const liabilities = signals.contingent_liabilities ?? []
  const outlook = (signals.management_outlook ?? "").trim()
  const fy = payload?.fiscal_year
  const published = formatDate(payload?.published_at ?? payload?.generated_at)

  // PR #613 extended fields — extracted with explicit "is filled"
  // guards so empty arrays / all-null objects don't render an empty
  // section header.
  const riskFactors = (signals.risk_factors ?? []).filter(
    (r) => isFilled(r?.category) || isFilled(r?.description) || isFilled(r?.mitigation),
  )
  const esg = signals.esg_metrics ?? null
  const esgFilled = hasAnyFilled(esg as Record<string, unknown> | null)
  const governance = signals.governance ?? null
  const governanceFilled = hasAnyFilled(governance as Record<string, unknown> | null)
  const workforce = signals.workforce_metrics ?? null
  const workforceFilled = hasAnyFilled(workforce as Record<string, unknown> | null)
  const customer = signals.customer_concentration ?? null
  const customerFilled =
    isFilled(customer?.top_10_customer_pct_revenue) ||
    (Array.isArray(customer?.geographic_split) && (customer?.geographic_split?.length ?? 0) > 0) ||
    (Array.isArray(customer?.channel_split) && (customer?.channel_split?.length ?? 0) > 0)
  const opKpis = signals.operational_kpis ?? null
  const opKpisMetricsEntries = opKpis?.metrics
    ? Object.entries(opKpis.metrics).filter(([, v]) => isFilled(v))
    : []
  const opKpisFilled = isFilled(opKpis?.industry) || opKpisMetricsEntries.length > 0
  const subsidiaries = (signals.subsidiary_summary ?? []).filter((s) =>
    isFilled(s?.name) ||
    isFilled(s?.country) ||
    isFilled(s?.revenue_cr) ||
    isFilled(s?.pat_cr) ||
    isFilled(s?.networth_cr) ||
    isFilled(s?.ownership_pct),
  )
  const dividends = (signals.dividend_history ?? []).filter((d) =>
    isFilled(d?.fiscal_year) ||
    isFilled(d?.total_dps_rs) ||
    isFilled(d?.interim_dps_rs) ||
    isFilled(d?.final_dps_rs) ||
    isFilled(d?.special_dps_rs) ||
    isFilled(d?.payout_ratio_pct),
  )
  const capitalActions = (signals.capital_actions ?? []).filter((c) =>
    isFilled(c?.type) ||
    isFilled(c?.date) ||
    isFilled(c?.ratio_or_price) ||
    isFilled(c?.amount_cr),
  )
  const strategicPriorities = (signals.strategic_priorities ?? []).filter((p) =>
    isFilled(p?.priority) || isFilled(p?.target) || isFilled(p?.timeline),
  )

  return (
    <div
      className="bg-bg rounded-2xl border border-border p-4"
      data-testid="ar-signals-panel"
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">
            Annual Report Signals
          </h2>
          <p className="text-[11px] text-caption mt-0.5">
            Structured extraction from the latest annual report.
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

      {/* Section 1: Segment data — DEFAULT EXPANDED */}
      <Collapsible
        id="ar-segments"
        title="Segment data"
        defaultOpen
        testId="ar-section-segments"
      >
        {segments.length === 0 ? (
          <p className="text-xs italic text-caption">
            No segment breakdown disclosed in this AR.
          </p>
        ) : (
          <ul className="space-y-2">
            {segments.slice(0, 8).map((s, i) => {
              const label =
                (s.name && String(s.name).trim()) ||
                (s.segment && String(s.segment).trim()) ||
                "Segment"
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
      </Collapsible>

      {/* Section 2: Capex commitments */}
      <Collapsible
        id="ar-capex"
        title="Capex commitments"
        testId="ar-section-capex"
      >
        {capex.length === 0 ? (
          <p className="text-xs italic text-caption">
            No capex commitments disclosed.
          </p>
        ) : (
          <ul className="space-y-2">
            {capex.slice(0, 6).map((c, i) => {
              const when = c.timeline || c.fy
              const title = c.description || c.project
              const hasAmount =
                c.amount_cr !== undefined && c.amount_cr !== null
              return (
                <li
                  key={i}
                  className="border border-border rounded-lg p-3 bg-surface/40"
                >
                  <div className="flex items-start justify-between gap-2 mb-1">
                    {title ? (
                      <span className="text-xs font-medium text-ink">
                        {title}
                      </span>
                    ) : (
                      <span className="text-xs font-medium text-ink">
                        Capex commitment
                      </span>
                    )}
                    {when && (
                      <span className="text-[10px] uppercase tracking-wide text-caption whitespace-nowrap">
                        {when}
                      </span>
                    )}
                  </div>
                  {hasAmount && (
                    <p className="text-[11px] text-caption">
                      {formatCr(c.amount_cr)}
                    </p>
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
      </Collapsible>

      {/* Section 3: Related-party transactions */}
      <Collapsible
        id="ar-rpt"
        title="Related-party transactions"
        testId="ar-section-rpt"
      >
        {rpts.length === 0 ? (
          <p className="text-xs italic text-caption">
            No material RPTs disclosed.
          </p>
        ) : (
          <ul className="space-y-2">
            {rpts.slice(0, 6).map((r, i) => {
              const who =
                (r.party && String(r.party).trim()) ||
                (r.counterparty && String(r.counterparty).trim()) ||
                "Counterparty"
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
                  {(r.amount_cr !== undefined && r.amount_cr !== null) || r.fy ? (
                    <p className="text-[11px] text-caption">
                      {r.amount_cr !== undefined && r.amount_cr !== null
                        ? formatCr(r.amount_cr)
                        : ""}
                      {r.amount_cr !== undefined &&
                      r.amount_cr !== null &&
                      r.fy
                        ? " · "
                        : ""}
                      {r.fy ?? ""}
                    </p>
                  ) : null}
                </li>
              )
            })}
          </ul>
        )}
      </Collapsible>

      {/* Section 4: Auditor flags */}
      <Collapsible
        id="ar-auditor"
        title="Auditor flags"
        testId="ar-section-auditor"
      >
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
      </Collapsible>

      {/* Section 5: Contingent liabilities */}
      <Collapsible
        id="ar-liabilities"
        title="Contingent liabilities"
        testId="ar-section-liabilities"
      >
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
      </Collapsible>

      {/* Section 6: Management outlook */}
      <Collapsible
        id="ar-outlook"
        title="Management outlook"
        testId="ar-section-outlook"
      >
        {!outlook ? (
          <p className="text-xs italic text-caption">
            No MD&amp;A narrative captured.
          </p>
        ) : (
          <p className="text-xs italic text-ink leading-relaxed">
            &ldquo;{outlook}&rdquo;
          </p>
        )}
      </Collapsible>

      {/* Section 7: Risk factors (PR #613) */}
      {riskFactors.length > 0 && (
        <Collapsible
          id="ar-risk-factors"
          title="Risk factors"
          testId="ar-section-risk-factors"
        >
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] border-collapse hidden md:table">
              <thead>
                <tr className="text-left text-caption uppercase tracking-wide">
                  <th className="py-1 pr-3 font-semibold">Category</th>
                  <th className="py-1 pr-3 font-semibold">Description</th>
                  <th className="py-1 font-semibold">Mitigation</th>
                </tr>
              </thead>
              <tbody>
                {riskFactors.map((r, i) => (
                  <tr key={i} className="border-t border-border align-top">
                    <td className="py-1.5 pr-3 text-ink">{r.category ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-caption">{r.description ?? "—"}</td>
                    <td className="py-1.5 text-caption">{r.mitigation ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {/* Mobile: stack each row */}
            <ul className="md:hidden space-y-2">
              {riskFactors.map((r, i) => (
                <li key={i} className="border border-border rounded-lg p-3 bg-surface/40">
                  {r.category && (
                    <div className="text-xs font-medium text-ink mb-1">{r.category}</div>
                  )}
                  {r.description && (
                    <p className="text-[11px] text-caption">{r.description}</p>
                  )}
                  {r.mitigation && (
                    <p className="text-[11px] text-caption mt-1">
                      <span className="uppercase tracking-wide">Mitigation: </span>
                      {r.mitigation}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </Collapsible>
      )}

      {/* Section 8: ESG metrics (PR #613) */}
      {esgFilled && esg && (
        <Collapsible
          id="ar-esg"
          title="ESG metrics"
          testId="ar-section-esg"
        >
          <KpiGrid
            tiles={[
              { label: "Scope 1 (tCO2e)", value: formatNumber(esg.scope1_emissions_tco2e), show: isFilled(esg.scope1_emissions_tco2e) },
              { label: "Scope 2 (tCO2e)", value: formatNumber(esg.scope2_emissions_tco2e), show: isFilled(esg.scope2_emissions_tco2e) },
              { label: "Scope 3 (tCO2e)", value: formatNumber(esg.scope3_emissions_tco2e), show: isFilled(esg.scope3_emissions_tco2e) },
              { label: "Renewable energy", value: formatPctLevel(esg.renewable_energy_pct), show: isFilled(esg.renewable_energy_pct) },
              { label: "Water (kl)", value: formatNumber(esg.water_withdrawal_kl), show: isFilled(esg.water_withdrawal_kl) },
              { label: "Female workforce", value: formatPctLevel(esg.gender_ratio_pct_female_workforce), show: isFilled(esg.gender_ratio_pct_female_workforce) },
              { label: "LTIFR", value: formatNumber(esg.lost_time_injury_frequency_rate), show: isFilled(esg.lost_time_injury_frequency_rate) },
              { label: "CSR spend", value: formatCr(esg.csr_spend_cr), show: isFilled(esg.csr_spend_cr) },
            ]}
          />
          {esg.note && (
            <p className="mt-2 text-[11px] italic text-caption">{esg.note}</p>
          )}
        </Collapsible>
      )}

      {/* Section 9: Governance signals (PR #613) */}
      {governanceFilled && governance && (
        <Collapsible
          id="ar-governance"
          title="Governance signals"
          testId="ar-section-governance"
        >
          <KpiGrid
            tiles={[
              { label: "Promoter pledge", value: formatPctLevel(governance.promoter_pledge_pct), show: isFilled(governance.promoter_pledge_pct) },
              { label: "Promoter holding", value: formatPctLevel(governance.promoter_shareholding_pct), show: isFilled(governance.promoter_shareholding_pct) },
              { label: "Board independence", value: formatPctLevel(governance.board_independence_pct), show: isFilled(governance.board_independence_pct) },
              { label: "Auditor remuneration", value: formatCr(governance.auditor_remuneration_cr), show: isFilled(governance.auditor_remuneration_cr) },
              { label: "Regulatory penalties", value: formatCr(governance.regulatory_penalties_cr), show: isFilled(governance.regulatory_penalties_cr) },
              { label: "Whistleblower complaints", value: formatNumber(governance.whistleblower_complaints_count), show: isFilled(governance.whistleblower_complaints_count) },
              { label: "Harassment complaints", value: formatNumber(governance.sexual_harassment_complaints_count), show: isFilled(governance.sexual_harassment_complaints_count) },
            ]}
          />
          {governance.note && (
            <p className="mt-2 text-[11px] italic text-caption">{governance.note}</p>
          )}
        </Collapsible>
      )}

      {/* Section 10: Workforce metrics (PR #613) */}
      {workforceFilled && workforce && (
        <Collapsible
          id="ar-workforce"
          title="Workforce metrics"
          testId="ar-section-workforce"
        >
          <KpiGrid
            tiles={[
              { label: "Headcount", value: formatNumber(workforce.total_headcount), show: isFilled(workforce.total_headcount) },
              { label: "Attrition", value: formatPctLevel(workforce.attrition_pct), show: isFilled(workforce.attrition_pct) },
              { label: "Female %", value: formatPctLevel(workforce.gender_ratio_pct_female), show: isFilled(workforce.gender_ratio_pct_female) },
              { label: "Training hrs/employee", value: formatNumber(workforce.training_hours_per_employee), show: isFilled(workforce.training_hours_per_employee) },
              { label: "Employee cost / revenue", value: formatPctLevel(workforce.employee_cost_pct_revenue), show: isFilled(workforce.employee_cost_pct_revenue) },
            ]}
          />
          {workforce.note && (
            <p className="mt-2 text-[11px] italic text-caption">{workforce.note}</p>
          )}
        </Collapsible>
      )}

      {/* Section 11: Customer concentration (PR #613) */}
      {customerFilled && customer && (
        <Collapsible
          id="ar-customer"
          title="Customer concentration"
          testId="ar-section-customer"
        >
          {isFilled(customer.top_10_customer_pct_revenue) && (
            <p className="text-xs text-ink mb-2">
              Top 10 customers:{" "}
              <span className="font-medium">
                {formatPctLevel(customer.top_10_customer_pct_revenue)}
              </span>{" "}
              of revenue
            </p>
          )}
          {Array.isArray(customer.geographic_split) && customer.geographic_split.length > 0 && (
            <div className="mb-3">
              <p className="text-[10px] uppercase tracking-wide text-caption mb-1">
                Geographic split
              </p>
              <SplitTable
                rows={customer.geographic_split}
                keyLabel="Region"
                keyField="region"
              />
            </div>
          )}
          {Array.isArray(customer.channel_split) && customer.channel_split.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wide text-caption mb-1">
                Channel split
              </p>
              <SplitTable
                rows={customer.channel_split}
                keyLabel="Channel"
                keyField="channel"
              />
            </div>
          )}
          {customer.note && (
            <p className="mt-2 text-[11px] italic text-caption">{customer.note}</p>
          )}
        </Collapsible>
      )}

      {/* Section 12: Operational KPIs (PR #613) */}
      {opKpisFilled && opKpis && (
        <Collapsible
          id="ar-opkpis"
          title="Operational KPIs"
          testId="ar-section-operational-kpis"
        >
          {opKpis.industry && (
            <p className="text-[11px] text-caption mb-2">
              Industry:{" "}
              <span className="text-ink font-medium">{opKpis.industry}</span>
            </p>
          )}
          {opKpisMetricsEntries.length > 0 && (
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5 text-[11px]">
              {opKpisMetricsEntries.map(([k, v]) => (
                <div key={k} className="flex justify-between border-b border-border/40 py-1">
                  <dt className="text-caption">{k.replace(/_/g, " ")}</dt>
                  <dd className="text-ink font-medium">{formatNumber(v as number | string)}</dd>
                </div>
              ))}
            </dl>
          )}
          {opKpis.note && (
            <p className="mt-2 text-[11px] italic text-caption">{opKpis.note}</p>
          )}
        </Collapsible>
      )}

      {/* Section 13: Subsidiary summary (PR #613) */}
      {subsidiaries.length > 0 && (
        <Collapsible
          id="ar-subsidiaries"
          title="Subsidiary summary"
          testId="ar-section-subsidiaries"
        >
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] border-collapse hidden md:table">
              <thead>
                <tr className="text-left text-caption uppercase tracking-wide">
                  <th className="py-1 pr-3 font-semibold">Name</th>
                  <th className="py-1 pr-3 font-semibold">Country</th>
                  <th className="py-1 pr-3 font-semibold text-right">Revenue</th>
                  <th className="py-1 pr-3 font-semibold text-right">PAT</th>
                  <th className="py-1 pr-3 font-semibold text-right">Net worth</th>
                  <th className="py-1 font-semibold text-right">Ownership</th>
                </tr>
              </thead>
              <tbody>
                {subsidiaries.map((s, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="py-1.5 pr-3 text-ink">{s.name ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-caption">{s.country ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-right text-caption">{formatCr(s.revenue_cr)}</td>
                    <td className="py-1.5 pr-3 text-right text-caption">{formatCr(s.pat_cr)}</td>
                    <td className="py-1.5 pr-3 text-right text-caption">{formatCr(s.networth_cr)}</td>
                    <td className="py-1.5 text-right text-caption">{formatPctLevel(s.ownership_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul className="md:hidden space-y-2">
              {subsidiaries.map((s, i) => (
                <li key={i} className="border border-border rounded-lg p-3 bg-surface/40">
                  <div className="flex items-baseline justify-between gap-2 mb-1">
                    <span className="text-xs font-medium text-ink">{s.name ?? "—"}</span>
                    {s.country && (
                      <span className="text-[10px] uppercase tracking-wide text-caption">{s.country}</span>
                    )}
                  </div>
                  <p className="text-[11px] text-caption">
                    Revenue {formatCr(s.revenue_cr)} · PAT {formatCr(s.pat_cr)}
                  </p>
                  <p className="text-[11px] text-caption">
                    Net worth {formatCr(s.networth_cr)} · Ownership {formatPctLevel(s.ownership_pct)}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </Collapsible>
      )}

      {/* Section 14: Dividend history (PR #613) */}
      {dividends.length > 0 && (
        <Collapsible
          id="ar-dividends"
          title="Dividend history"
          testId="ar-section-dividends"
        >
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] border-collapse hidden md:table">
              <thead>
                <tr className="text-left text-caption uppercase tracking-wide">
                  <th className="py-1 pr-3 font-semibold">FY</th>
                  <th className="py-1 pr-3 font-semibold text-right">Interim DPS</th>
                  <th className="py-1 pr-3 font-semibold text-right">Final DPS</th>
                  <th className="py-1 pr-3 font-semibold text-right">Special DPS</th>
                  <th className="py-1 pr-3 font-semibold text-right">Total DPS</th>
                  <th className="py-1 font-semibold text-right">Payout</th>
                </tr>
              </thead>
              <tbody>
                {dividends.map((d, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="py-1.5 pr-3 text-ink">{d.fiscal_year ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-right text-caption">{formatNumber(d.interim_dps_rs)}</td>
                    <td className="py-1.5 pr-3 text-right text-caption">{formatNumber(d.final_dps_rs)}</td>
                    <td className="py-1.5 pr-3 text-right text-caption">{formatNumber(d.special_dps_rs)}</td>
                    <td className="py-1.5 pr-3 text-right text-ink font-medium">{formatNumber(d.total_dps_rs)}</td>
                    <td className="py-1.5 text-right text-caption">{formatPctLevel(d.payout_ratio_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul className="md:hidden space-y-2">
              {dividends.map((d, i) => (
                <li key={i} className="border border-border rounded-lg p-3 bg-surface/40">
                  <div className="text-xs font-medium text-ink mb-1">FY {d.fiscal_year ?? "—"}</div>
                  <p className="text-[11px] text-caption">
                    Total DPS Rs {formatNumber(d.total_dps_rs)} · Payout {formatPctLevel(d.payout_ratio_pct)}
                  </p>
                  <p className="text-[11px] text-caption">
                    Interim {formatNumber(d.interim_dps_rs)} · Final {formatNumber(d.final_dps_rs)} · Special {formatNumber(d.special_dps_rs)}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </Collapsible>
      )}

      {/* Section 15: Capital actions (PR #613) */}
      {capitalActions.length > 0 && (
        <Collapsible
          id="ar-capital-actions"
          title="Capital actions"
          testId="ar-section-capital-actions"
        >
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] border-collapse hidden md:table">
              <thead>
                <tr className="text-left text-caption uppercase tracking-wide">
                  <th className="py-1 pr-3 font-semibold">Type</th>
                  <th className="py-1 pr-3 font-semibold">Date</th>
                  <th className="py-1 pr-3 font-semibold">Ratio / Price</th>
                  <th className="py-1 font-semibold text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {capitalActions.map((c, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="py-1.5 pr-3 text-ink">{c.type ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-caption">{c.date ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-caption">{c.ratio_or_price ?? "—"}</td>
                    <td className="py-1.5 text-right text-caption">{formatCr(c.amount_cr)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul className="md:hidden space-y-2">
              {capitalActions.map((c, i) => (
                <li key={i} className="border border-border rounded-lg p-3 bg-surface/40">
                  <div className="flex items-baseline justify-between gap-2 mb-1">
                    <span className="text-xs font-medium text-ink">{c.type ?? "—"}</span>
                    {c.date && (
                      <span className="text-[10px] uppercase tracking-wide text-caption">{c.date}</span>
                    )}
                  </div>
                  <p className="text-[11px] text-caption">
                    {c.ratio_or_price ?? "—"} · {formatCr(c.amount_cr)}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </Collapsible>
      )}

      {/* Section 16: Strategic priorities (PR #613) */}
      {strategicPriorities.length > 0 && (
        <Collapsible
          id="ar-strategic-priorities"
          title="Strategic priorities"
          testId="ar-section-strategic-priorities"
        >
          <ul className="space-y-2">
            {strategicPriorities.map((p, i) => (
              <li
                key={i}
                className="border border-border rounded-lg p-3 bg-surface/40"
              >
                <div className="flex items-baseline justify-between gap-2 mb-1">
                  <span className="text-xs font-medium text-ink">
                    {p.priority ?? "—"}
                  </span>
                  {p.timeline && (
                    <span className="text-[10px] uppercase tracking-wide text-caption">
                      {p.timeline}
                    </span>
                  )}
                </div>
                {p.target && (
                  <p className="text-[11px] text-caption">
                    <span className="uppercase tracking-wide">Target: </span>
                    {p.target}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </Collapsible>
      )}

      <p className="mt-4 text-[10px] text-caption leading-relaxed">
        Signals are AI-extracted from the annual report. They describe
        what the AR disclosed and are not investment advice.
      </p>
    </div>
  )
}

// ---- helpers used only inside this file --------------------------

interface KpiTile {
  label: string
  value: string
  show: boolean
}

function KpiGrid({ tiles }: { tiles: KpiTile[] }) {
  const visible = tiles.filter((t) => t.show)
  if (visible.length === 0) {
    return (
      <p className="text-xs italic text-caption">
        No metrics disclosed.
      </p>
    )
  }
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
      {visible.map((t, i) => (
        <div
          key={i}
          className="border border-border rounded-lg p-2 bg-surface/40"
        >
          <p className="text-[10px] uppercase tracking-wide text-caption">
            {t.label}
          </p>
          <p className="text-xs font-medium text-ink mt-0.5">{t.value}</p>
        </div>
      ))}
    </div>
  )
}

function SplitTable({
  rows,
  keyLabel,
  keyField,
}: {
  rows: SplitRow[]
  keyLabel: string
  keyField: "region" | "channel"
}) {
  const filtered = rows.filter(
    (r) => isFilled(r?.[keyField]) || isFilled(r?.pct_revenue),
  )
  if (filtered.length === 0) return null
  return (
    <table className="w-full text-[11px] border-collapse">
      <thead>
        <tr className="text-left text-caption uppercase tracking-wide">
          <th className="py-1 pr-3 font-semibold">{keyLabel}</th>
          <th className="py-1 font-semibold text-right">% of revenue</th>
        </tr>
      </thead>
      <tbody>
        {filtered.map((r, i) => (
          <tr key={i} className="border-t border-border">
            <td className="py-1.5 pr-3 text-ink">{r[keyField] ?? "—"}</td>
            <td className="py-1.5 text-right text-caption">
              {formatPctLevel(r.pct_revenue)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
