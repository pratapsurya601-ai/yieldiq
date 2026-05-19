/**
 * Shared types for admin-only frontend pages.
 *
 * Keep this in sync with the `to_dict()` output of the corresponding
 * backend dataclasses — see references below. Admin pages are gated
 * by both an ADMIN_EMAILS allow-list in the page and `require_admin`
 * on the server, so these shapes never leak to non-admin users.
 */

/**
 * One row of `GET /api/v1/admin/benchmark-outliers`.
 *
 * Mirrors `OutlierRow` in
 * `backend/services/benchmark_reconciliation_service.py`. The endpoint
 * itself is defined at the bottom of `backend/routers/admin.py` and was
 * introduced as Layer A of the benchmark-reconciliation framework
 * (design doc: `docs/design/benchmark-reconciliation-framework.md §6.1`).
 *
 * NOTE: `consensus_fv` is present here because the payload only flows
 * to the admin dashboard. The user-facing `CaveatInfo` path deliberately
 * omits the consensus number to avoid leaking analyst targets.
 */
export interface BenchmarkOutlier {
  ticker: string
  sector: string | null
  our_fv: number
  consensus_fv: number
  /** Signed fraction (e.g. -0.33 = our_fv 33% below consensus). */
  delta_pct: number
  /** "over" if our_fv > consensus_fv, otherwise "under". */
  direction: "over" | "under"
  analyst_count: number
  /** Provider that supplied the consensus target. */
  source: string
  /** ISO8601 timestamp the consensus row was fetched at. */
  fetched_at: string
  computed_at: string | null
}

/**
 * Envelope returned by `GET /api/v1/admin/benchmark-outliers`.
 *
 * `threshold_pct` is the *fraction* used to filter the rows (the server
 * clamps it to [0.01, 5.0]); we surface it in the UI so the operator can
 * see what cut produced the list.
 */
export interface BenchmarkOutliersResponse {
  generated_at: string
  threshold_pct: number
  min_analysts: number
  direction: "both" | "over" | "under"
  count: number
  rows: BenchmarkOutlier[]
}
