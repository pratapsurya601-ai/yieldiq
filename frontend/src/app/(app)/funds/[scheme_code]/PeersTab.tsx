/**
 * PeersTab — the Peers section of the fund Asset Page.
 *
 * Server-renderable. Consumes the optional `peers` array (same SEBI
 * sub-category) plus the `category_stats` aggregate. Renders a STRICTLY
 * DESCRIPTIVE comparison table — the current scheme, up to three peers,
 * and a category-average pseudo-row — with score, 1Y / 3Y return, TER,
 * and Riskometer.
 *
 * SEBI posture: this is comparative reference data only. No "best",
 * "top", ranking-verdict, or advisory copy anywhere. Peers are ordered
 * for stable display, NOT ranked. The caption states this explicitly.
 *
 * Defensive: empty-states when no peers are present (block absent until
 * the parallel backend PR ships).
 */
import Link from "next/link"

import type {
  Fund,
  FundCategoryStats,
  FundPeer,
  FundReturnsCache,
} from "@/types/api"
import { RISKOMETER_TONE } from "@/lib/fund-riskometer"

import {
  fmtReturnPct,
  fmtTerPct,
  normalizeFundName,
  scoreTint,
} from "../FundCard"
import TabEmptyState from "./TabEmptyState"
import { DASH, present } from "./fund-format"

// A normalised row the table renders. `href` is null for the synthetic
// category-average row and for the current scheme (no self-link).
interface Row {
  key: string
  name: string
  amc: string | null
  href: string | null
  isCurrent: boolean
  isCategory: boolean
  score: number | null
  ret1y: number | null
  ret3y: number | null
  terDirect: number | null
  riskLabel: string | null
  riskCls: string | null
}

function returnCell(frac: number | null) {
  if (!present(frac)) return <span className="text-caption">{DASH}</span>
  const tone = frac >= 0 ? "text-success" : "text-warning"
  return (
    <span className={`num font-medium tabular-nums ${tone}`}>
      {fmtReturnPct(frac, true)}
    </span>
  )
}

export default function PeersTab({
  fund,
  metrics,
  peers,
  categoryStats,
}: {
  fund: Fund
  metrics: FundReturnsCache | null
  peers?: FundPeer[] | null
  categoryStats?: FundCategoryStats | null
}) {
  const peerList = (peers ?? []).filter(
    (p) => p.scheme_code !== fund.scheme_code,
  )

  if (peerList.length === 0) {
    return (
      <TabEmptyState
        title="Peer comparison is being prepared"
        message="Same-category peer data is compiling — check back soon."
      />
    )
  }

  const currentRisk = fund.riskometer_level
    ? RISKOMETER_TONE[fund.riskometer_level]
    : null

  // Current scheme row first, then up to three peers (stable order).
  const rows: Row[] = []

  rows.push({
    key: `current-${fund.scheme_code}`,
    name: normalizeFundName(fund.scheme_name),
    amc: fund.amc,
    href: null,
    isCurrent: true,
    isCategory: false,
    score: metrics?.yieldiq_fund_score ?? null,
    ret1y: metrics?.ret_1y ?? null,
    ret3y: metrics?.ret_3y ?? null,
    terDirect: metrics?.ter_direct ?? null,
    riskLabel: currentRisk?.label ?? null,
    riskCls: currentRisk?.cls ?? null,
  })

  for (const p of peerList.slice(0, 3)) {
    const risk = p.riskometer_level ? RISKOMETER_TONE[p.riskometer_level] : null
    rows.push({
      key: `peer-${p.scheme_code}`,
      name: normalizeFundName(p.scheme_name),
      amc: p.amc ?? null,
      href: `/funds/${encodeURIComponent(p.scheme_code)}`,
      isCurrent: false,
      isCategory: false,
      score: p.fund_score ?? null,
      ret1y: p.ret_1y ?? null,
      ret3y: p.ret_3y ?? null,
      terDirect: p.ter_direct ?? null,
      riskLabel: risk?.label ?? null,
      riskCls: risk?.cls ?? null,
    })
  }

  // Category-average pseudo-row, when aggregate stats are present.
  if (categoryStats) {
    const anyStat =
      present(categoryStats.avg_cagr_1y) ||
      present(categoryStats.avg_cagr_3y) ||
      present(categoryStats.avg_ter)
    if (anyStat) {
      rows.push({
        key: "category-average",
        name: categoryStats.sub_category
          ? `Category average — ${categoryStats.sub_category}`
          : "Category average",
        amc: present(categoryStats.n_funds)
          ? `${categoryStats.n_funds} funds`
          : null,
        href: null,
        isCurrent: false,
        isCategory: true,
        score: null,
        ret1y: categoryStats.avg_cagr_1y ?? null,
        ret3y: categoryStats.avg_cagr_3y ?? null,
        terDirect: categoryStats.avg_ter ?? null,
        riskLabel: null,
        riskCls: null,
      })
    }
  }

  return (
    <div className="grid gap-4">
      <section className="rounded-lg border border-border bg-raised p-4">
        <h3 className="mb-3 text-base font-semibold text-ink">
          Same sub-category
        </h3>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-caption">
                <th className="py-2 pr-4 font-medium">Scheme</th>
                <th className="py-2 pr-4 text-right font-medium">Score</th>
                <th className="py-2 pr-4 text-right font-medium">1Y</th>
                <th className="py-2 pr-4 text-right font-medium">3Y</th>
                <th className="py-2 pr-4 text-right font-medium">TER (Direct)</th>
                <th className="py-2 pr-4 font-medium">Riskometer</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((r) => {
                const ter = present(r.terDirect) ? fmtTerPct(r.terDirect) : null
                return (
                  <tr
                    key={r.key}
                    className={
                      r.isCurrent
                        ? "bg-tone-info-bg/40"
                        : r.isCategory
                          ? "bg-surface/60"
                          : ""
                    }
                  >
                    <td className="py-2.5 pr-4">
                      <div className="flex flex-col">
                        {r.href ? (
                          <Link
                            href={r.href}
                            className="font-medium text-ink hover:text-brand hover:underline"
                          >
                            {r.name}
                          </Link>
                        ) : (
                          <span
                            className={
                              r.isCategory
                                ? "font-medium italic text-body"
                                : "font-semibold text-ink"
                            }
                          >
                            {r.name}
                            {r.isCurrent ? (
                              <span className="ml-2 rounded-full bg-tone-info-bg px-1.5 py-0.5 text-[10px] font-medium text-tone-info-fg">
                                This fund
                              </span>
                            ) : null}
                          </span>
                        )}
                        {r.amc ? (
                          <span className="text-[11px] text-caption">{r.amc}</span>
                        ) : null}
                      </div>
                    </td>
                    <td className="py-2.5 pr-4 text-right">
                      {present(r.score) ? (
                        <span
                          className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ${scoreTint(r.score)}`}
                        >
                          {Math.round(r.score)}
                        </span>
                      ) : (
                        <span className="text-caption">{DASH}</span>
                      )}
                    </td>
                    <td className="py-2.5 pr-4 text-right">{returnCell(r.ret1y)}</td>
                    <td className="py-2.5 pr-4 text-right">{returnCell(r.ret3y)}</td>
                    <td className="num py-2.5 pr-4 text-right tabular-nums text-body">
                      {ter ?? DASH}
                    </td>
                    <td className="py-2.5 pr-4">
                      {r.riskLabel && r.riskCls ? (
                        <span
                          className={`rounded-full ${r.riskCls} px-2 py-0.5 text-[11px] font-medium`}
                        >
                          {r.riskLabel}
                        </span>
                      ) : (
                        <span className="text-caption">{DASH}</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-caption">
          Peers in the same SEBI sub-category, ordered for stable display — not a recommendation. Returns are CAGR for 3Y and absolute for 1Y. {/* sebi-allow: recommendation */}
        </p>
      </section>
    </div>
  )
}
