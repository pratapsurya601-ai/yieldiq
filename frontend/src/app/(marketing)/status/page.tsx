import type { Metadata } from "next"
import Link from "next/link"

/**
 * /status — public uptime / status page.
 *
 * Server Component. Fetches the backend's /api/v1/public/status
 * payload at render time with `next: { revalidate: 60 }` so each
 * Vercel-edge node refreshes the snapshot once a minute.
 *
 * Layout:
 *   1. Banner          — overall status, big colored pill
 *   2. Components grid — 4 cards (API, DB, Pipeline, Data freshness)
 *   3. Incidents (30d) — table with date, severity, title, link
 *   4. Footer          — auto-refresh hint, "subscribe (coming soon)"
 *
 * Replaces the previous app/status/route.ts placeholder that
 * 307-redirected to yieldiq.betterstack.com — that redirect existed
 * only because we hadn't built this page yet.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// ── Types matching backend /api/v1/public/status ──────────────────
type ComponentStatus = "operational" | "degraded" | "down"

interface ApiComponent {
  status: ComponentStatus
  latency_ms: number | null
}
interface DbComponent {
  status: ComponentStatus
  latency_ms: number | null
}
interface PipelineComponent {
  status: ComponentStatus
  last_compute_ms: number | null
  last_computed_at?: string | null
}
interface FreshnessComponent {
  status: ComponentStatus
  last_backfill: string | null
  tickers_covered: number | null
}
interface Incident {
  date: string
  severity: "minor" | "major" | "critical" | string
  title: string
  resolved: boolean
  url?: string | null
}
interface StatusPayload {
  status: ComponentStatus
  version: string
  computed_at: string
  components: {
    api: ApiComponent
    database: DbComponent
    analysis_pipeline: PipelineComponent
    data_freshness: FreshnessComponent
  }
  incidents_30d: Incident[]
}

// ── Next.js page-level config ─────────────────────────────────────
// Server-side ISR: each edge node refreshes once a minute, so users
// see fresh signal without us hammering the backend on every hit.
export const revalidate = 60

export function generateMetadata(): Metadata {
  const title = "YieldIQ status — uptime & incidents"
  const description =
    "Live status of the YieldIQ API, database, analysis pipeline, and data freshness. Plus the last 30 days of incidents."
  return {
    title,
    description,
    alternates: { canonical: "https://yieldiq.in/status" },
    openGraph: {
      title,
      description,
      url: "https://yieldiq.in/status",
      siteName: "YieldIQ",
      type: "website",
      locale: "en_IN",
      images: [
        {
          url: "https://yieldiq.in/icon-512.png",
          width: 512,
          height: 512,
          alt: "YieldIQ",
        },
      ],
    },
    twitter: {
      card: "summary",
      title,
      description,
      images: ["https://yieldiq.in/icon-512.png"],
    },
  }
}

// ── Data fetch (server) ───────────────────────────────────────────
async function fetchStatus(): Promise<StatusPayload | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/status`, {
      next: { revalidate: 60 },
    })
    if (!res.ok) return null
    return (await res.json()) as StatusPayload
  } catch {
    return null
  }
}

// ── Visual helpers ────────────────────────────────────────────────
function statusLabel(s: ComponentStatus): string {
  if (s === "operational") return "Operational"
  if (s === "degraded") return "Degraded"
  return "Down"
}

/** Tailwind class set keyed off component status. We use semantic
 * green/yellow/red rather than the brand palette — the whole point
 * of a status page is that "green" reads as "fine" at a glance. */
function statusClasses(s: ComponentStatus): {
  pill: string
  dot: string
  banner: string
  bannerText: string
} {
  if (s === "operational") {
    return {
      pill: "bg-green-100 text-green-900 ring-1 ring-green-300",
      dot: "bg-green-500",
      banner: "bg-green-50 border-green-300",
      bannerText: "text-green-900",
    }
  }
  if (s === "degraded") {
    return {
      pill: "bg-yellow-100 text-yellow-900 ring-1 ring-yellow-300",
      dot: "bg-yellow-500",
      banner: "bg-yellow-50 border-yellow-300",
      bannerText: "text-yellow-900",
    }
  }
  return {
    pill: "bg-red-100 text-red-900 ring-1 ring-red-300",
    dot: "bg-red-500",
    banner: "bg-red-50 border-red-300",
    bannerText: "text-red-900",
  }
}

function overallHeadline(s: ComponentStatus): string {
  if (s === "operational") return "All systems operational"
  if (s === "degraded") return "Some systems degraded"
  return "Major outage"
}

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toUTCString()
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  // Already YYYY-MM-DD
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toISOString().slice(0, 10)
}

// ── Card component ────────────────────────────────────────────────
function ComponentCard({
  title,
  status,
  metric,
}: {
  title: string
  status: ComponentStatus
  metric: string
}) {
  const c = statusClasses(status)
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-editorial text-base font-semibold text-ink">
          {title}
        </h3>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${c.pill}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} />
          {statusLabel(status)}
        </span>
      </div>
      <p className="text-sm text-body leading-relaxed">{metric}</p>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────
export default async function StatusPage() {
  const data = await fetchStatus()

  // If the backend itself can't be reached, render a "down" banner so
  // the page is still useful (and accurate).
  const fallback: StatusPayload = {
    status: "down",
    version: "unknown",
    computed_at: new Date().toISOString(),
    components: {
      api: { status: "down", latency_ms: null },
      database: { status: "down", latency_ms: null },
      analysis_pipeline: { status: "down", last_compute_ms: null },
      data_freshness: {
        status: "down",
        last_backfill: null,
        tickers_covered: null,
      },
    },
    incidents_30d: [],
  }
  const payload = data ?? fallback
  const banner = statusClasses(payload.status)

  // ── Per-component metric strings ────────────────────────────────
  const apiMetric =
    payload.components.api.latency_ms !== null
      ? `Endpoint reachable. Round-trip ${payload.components.api.latency_ms} ms.`
      : "Endpoint reachable."

  const dbMetric =
    payload.components.database.latency_ms !== null
      ? `Aiven Postgres ping: ${payload.components.database.latency_ms} ms.`
      : "Aiven Postgres unreachable."

  const pipeMs = payload.components.analysis_pipeline.last_compute_ms
  const pipeAt = payload.components.analysis_pipeline.last_computed_at
  const pipelineMetric = pipeAt
    ? `Last compute ${pipeMs ?? "—"} ms, ${formatTimestamp(pipeAt)}.`
    : "No recent compute recorded in the last 24 h."

  const fresh = payload.components.data_freshness
  const freshnessMetric =
    fresh.tickers_covered !== null
      ? `${fresh.tickers_covered.toLocaleString("en-IN")} active tickers; latest financials period ${
          fresh.last_backfill ?? "—"
        }.`
      : "Coverage data unavailable."

  return (
    <main className="bg-bg text-body">
      {/* ── Hero / banner ─────────────────────────────────────────── */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 pt-12 pb-8">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-4">
          YieldIQ status
        </p>
        <div
          className={`rounded-2xl border p-6 sm:p-8 ${banner.banner}`}
          role="status"
          aria-live="polite"
        >
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h1
                className={`font-editorial text-3xl sm:text-4xl font-semibold leading-tight ${banner.bannerText}`}
                style={{ fontVariationSettings: "'opsz' 64" }}
              >
                {overallHeadline(payload.status)}
              </h1>
              <p className="mt-2 text-sm text-body">
                Build {payload.version} · checked {formatTimestamp(payload.computed_at)}
              </p>
            </div>
            <span
              className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium ${banner.pill}`}
            >
              <span className={`h-2 w-2 rounded-full ${banner.dot}`} />
              {statusLabel(payload.status)}
            </span>
          </div>
        </div>
      </section>

      {/* ── Components grid ───────────────────────────────────────── */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 py-8 border-t border-border">
        <h2 className="font-editorial text-2xl sm:text-3xl font-semibold text-ink mb-6">
          Components
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <ComponentCard
            title="API"
            status={payload.components.api.status}
            metric={apiMetric}
          />
          <ComponentCard
            title="Database"
            status={payload.components.database.status}
            metric={dbMetric}
          />
          <ComponentCard
            title="Analysis pipeline"
            status={payload.components.analysis_pipeline.status}
            metric={pipelineMetric}
          />
          <ComponentCard
            title="Data freshness"
            status={payload.components.data_freshness.status}
            metric={freshnessMetric}
          />
        </div>
      </section>

      {/* ── Incidents (30d) ───────────────────────────────────────── */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 py-8 border-t border-border">
        <h2 className="font-editorial text-2xl sm:text-3xl font-semibold text-ink mb-2">
          Incidents — last 30 days
        </h2>
        <p className="text-sm text-caption mb-6">
          Every user-visible incident in the last 30 days, with a link to the
          post-mortem when one exists.
        </p>

        {payload.incidents_30d.length === 0 ? (
          <p className="text-sm text-body">
            No incidents reported in the last 30 days.
          </p>
        ) : (
          <ul
            className="rounded-2xl border border-border bg-surface px-5"
            aria-label="Incidents in the last 30 days"
          >
            {payload.incidents_30d.map((inc, i) => (
              <li
                key={`${inc.date}-${i}`}
                className="flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-1 py-3 border-b border-border last:border-b-0"
              >
                <div className="flex flex-col sm:flex-row sm:items-baseline gap-2">
                  <span className="text-xs text-caption uppercase tracking-wider w-24 shrink-0">
                    {formatDate(inc.date)}
                  </span>
                  <span className="text-sm text-ink">
                    {inc.url ? (
                      <Link
                        href={inc.url}
                        className="text-brand hover:underline underline-offset-4"
                      >
                        {inc.title}
                      </Link>
                    ) : (
                      inc.title
                    )}
                  </span>
                </div>
                <span
                  className={`text-xs uppercase tracking-wider ${
                    inc.resolved ? "text-caption" : "text-red-700"
                  }`}
                >
                  {inc.severity} · {inc.resolved ? "resolved" : "open"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── Footer ────────────────────────────────────────────────── */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 py-8 border-t border-border">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 text-sm text-caption">
          <p>
            Auto-refreshes every 60 seconds. Last checked{" "}
            {formatTimestamp(payload.computed_at)}.
          </p>
          <span aria-disabled="true" className="opacity-70">
            Get notified of incidents — coming soon
          </span>
        </div>

        <div className="mt-6 pt-6 border-t border-border flex flex-wrap gap-4 text-sm">
          <Link
            href="/legal/sla"
            className="text-brand hover:underline underline-offset-4"
          >
            See our SLA &rarr;
          </Link>
          <Link
            href="/about"
            className="text-body hover:text-ink transition-colors"
          >
            About
          </Link>
          <Link
            href="/methodology"
            className="text-body hover:text-ink transition-colors"
          >
            Methodology
          </Link>
        </div>
      </section>
    </main>
  )
}
