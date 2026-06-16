"use client"

/**
 * SectionPeersV2 (#sec-peers) — Peers & track record, on REAL data.
 *
 * PORTED visuals from app/demo/analysis-redesign/SectionPeers.tsx:
 *   - sortable peer table (tap a column header to sort, hover a row to
 *     cross-highlight its quadrant bubble),
 *   - value × quality quadrant (P/B on x, ROE on y, bubble size = market
 *     cap), and
 *   - the 24-month fair-value-vs-price history chart — JAGGED polyline +
 *     airy under-fade (§7.4), hover scrubber with dual tooltips, and
 *     model-change pennant flags stamped from the annotations feed.
 *
 * Real data wiring (all DEFERRED — gated by IntersectionObserver via
 * useInViewOnce so the queries fire only when the section is scrolled
 * into view, NOT on mount):
 *   - getPeers()            → PeerRow[]                 (table + quadrant)
 *   - getFVHistory()        → {date, fair_value, price, mos_pct}[] + the
 *                             FVHistorySummary (price-vs-FV jagged lines,
 *                             scrubber, and the track-record stat tiles)
 *   - getValuationHistory() → FairValueHistoryResponse.annotations[]
 *                             {date, cause_label, fv_delta_pct}
 *                             (model-change pennants)
 *
 * The peer endpoint carries its own `fair_value` per PeerRow; the
 * ESLint headline-FV invariant only restricts `signals.fairValue` and
 * `x.valuation.fair_value`, so `peer.fair_value` / `point.fair_value`
 * reads are clean. We do not surface a headline FV number here.
 *
 * SEBI: every static label is descriptive (P/B, ROE, "below fair
 * value", "fair value led price"). The annotation `cause_label` and the
 * peer `company_name` are backend-sourced strings (already SEBI-vetted
 * server-side) rendered as dynamic `{...}` — never static literals.
 */

import { useMemo, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { CircleCheck } from "lucide-react"

import {
  getPeers,
  getFVHistory,
  getValuationHistory,
  type PeerRow,
  type FVHistoryPoint,
} from "@/lib/api"
import type { FairValueAnnotation } from "@/types/api"
import { useInViewOnce, useReducedMotion } from "@/components/anim"
import { formatCurrency } from "@/lib/utils"
import { formatCrore, formatCompactCount, formatMultiple, formatPct } from "@/lib/formatNumbers"

import { DEMO_COLORS, TOKENS } from "@/app/demo/analysis-redesign/theme"
import { Kpi, Legend, Muted, Ribbon, Section, Subh, Swatch } from "@/app/demo/analysis-redesign/ui"

/* ------------------------------------------------------------------ */
/*  Section shell — fires the deferred peer / history queries only     */
/*  once the section enters the viewport (IntersectionObserver gate).  */
/* ------------------------------------------------------------------ */
export default function SectionPeersV2({ ticker }: { ticker: string }) {
  // IntersectionObserver gate. `inView` flips true once, when the
  // section first scrolls into view; the queries below stay disabled
  // until then, so nothing fans out on mount.
  const { ref, inView } = useInViewOnce<HTMLElement>(0)

  const peersQ = useQuery({
    queryKey: ["v2-peers", ticker],
    queryFn: () => getPeers(ticker),
    enabled: !!ticker && inView,
    staleTime: 60_000,
  })

  const historyQ = useQuery({
    queryKey: ["v2-fv-history", ticker, 2],
    queryFn: () => getFVHistory(ticker, 2),
    enabled: !!ticker && inView,
    staleTime: 60_000,
  })

  // Annotations (model-change pennants) come off the valuation-history
  // endpoint, which carries the SEBI-clean `cause_label` + `fv_delta_pct`
  // the demo's purple flags render.
  const annotationsQ = useQuery({
    queryKey: ["v2-valuation-history", ticker],
    queryFn: () => getValuationHistory(ticker),
    enabled: !!ticker && inView,
    staleTime: 60_000,
  })

  const [hoverPeer, setHoverPeer] = useState<string | null>(null)

  const peersResp = peersQ.data
  const peers = peersResp?.peers ?? []
  const mainTicker = peers.find((p) => p.is_main)?.ticker ?? ticker

  const historyResp = historyQ.data
  const points = historyResp?.data ?? []
  const summary = historyResp?.summary

  // Annotations confined to the chart's date window so a pennant never
  // lands off the plotted range.
  const annotations = useMemo<FairValueAnnotation[]>(() => {
    const anns = annotationsQ.data?.annotations ?? []
    if (points.length === 0) return []
    const first = points[0].date
    const last = points[points.length - 1].date
    return anns.filter((a) => a.date >= first && a.date <= last)
  }, [annotationsQ.data, points])

  return (
    <Section
      id="sec-peers"
      num="08"
      title="Peers & track record"
      innerRef={ref}
      ribbon={
        peersResp?.has_peers ? (
          <Ribbon tone="good" icon={<CircleCheck size={13} aria-hidden="true" />}>
            {peersResp.peers_count} in {peersResp.sector_label ?? "sector"}
          </Ribbon>
        ) : undefined
      }
    >
      {/* ── Peer table ────────────────────────────────────────────── */}
      <Subh>
        Compare with peers{" "}
        <span className="font-normal text-caption">
          — tap a column to sort, hover a row to find it on the map
        </span>
      </Subh>
      {peersQ.isLoading ? (
        <SkeletonBlock height={150} label="Loading peers" />
      ) : peers.length > 0 ? (
        <PeerTable peers={peers} mainTicker={mainTicker} hoverPeer={hoverPeer} onHover={setHoverPeer} />
      ) : (
        <Muted>No peer cohort is available for this company yet.</Muted>
      )}

      {/* ── Value × quality quadrant ──────────────────────────────── */}
      {peers.length > 1 && (
        <>
          <Subh className="mt-5">Value vs quality map</Subh>
          <ValueQualityQuadrant peers={peers} hoverPeer={hoverPeer} />
        </>
      )}

      {/* ── 24-month fair-value-vs-price history ──────────────────── */}
      <Subh className="mt-5">
        Track record — fair value vs price{" "}
        <span className="font-normal text-caption">— hover the chart</span>
      </Subh>
      {historyQ.isLoading ? (
        <SkeletonBlock height={170} label="Loading track record" />
      ) : points.length >= 2 ? (
        <HistoryChart ticker={ticker} points={points} annotations={annotations} />
      ) : (
        <Muted>
          {historyResp?.message ??
            "Fair-value history is still building for this company — it needs a few months of computed points."}
        </Muted>
      )}

      {/* Track-record stat tiles from the FVHistorySummary. */}
      {summary?.has_data && (
        <div className="mt-3.5 grid grid-cols-2 gap-2.5 md:grid-cols-3">
          {summary.pct_undervalued != null && (
            <Kpi
              label="Price below fair value"
              value={<span className="text-[17px]">{Math.round(summary.pct_undervalued)}%</span>}
              sub="of the window"
            />
          )}
          <Kpi
            label="Data points"
            value={<span className="text-[17px]">{summary.total_points}</span>}
          />
          {summary.data_start_date && (
            <Kpi
              label="History since"
              value={<span className="text-[15px]">{fmtMonth(summary.data_start_date)}</span>}
            />
          )}
        </div>
      )}
    </Section>
  )
}

/* ================================================================== */
/*  Sortable peer table                                               */
/* ================================================================== */

/** Display columns: [PeerRow key, header label]. Real fields only. */
const COLS: [keyof PeerRow, string][] = [
  ["company_name", "Company"],
  ["mos_pct", "Below FV"],
  ["pb_ratio", "P/B"],
  ["roe_pct", "ROE"],
  ["dividend_yield", "Div yld"],
  ["market_cap_cr", "Mkt cap"],
]

function fmtCell(k: keyof PeerRow, p: PeerRow): string {
  const v = p[k]
  if (k === "company_name") return shortName(p.company_name, p.ticker)
  if (v == null || !Number.isFinite(v as number)) return "—"
  const n = v as number
  if (k === "mos_pct") return formatPct(n, { signed: true, decimals: 0 })
  if (k === "pb_ratio") return formatMultiple(n)
  if (k === "roe_pct" || k === "dividend_yield") return formatPct(n)
  if (k === "market_cap_cr") return formatCrore(n)
  return String(n)
}

/** Compact a company name for the narrow table; falls back to ticker. */
function shortName(name: string | null, ticker: string): string {
  const base = (name && name.trim()) || ticker.replace(".NS", "").replace(".BO", "")
  return base.length > 18 ? base.slice(0, 17) + "…" : base
}

function PeerTable({
  peers,
  mainTicker,
  hoverPeer,
  onHover,
}: {
  peers: PeerRow[]
  mainTicker: string
  hoverPeer: string | null
  onHover: (t: string | null) => void
}) {
  // Default sort: largest discount (Below FV) first, nulls sink.
  const [sortKey, setSortKey] = useState<keyof PeerRow>("mos_pct")
  const [sortDir, setSortDir] = useState(-1)

  const rows = useMemo(() => {
    const copy = [...peers]
    copy.sort((a, b) => {
      if (sortKey === "company_name") {
        return shortName(a.company_name, a.ticker).localeCompare(shortName(b.company_name, b.ticker)) * sortDir
      }
      const av = a[sortKey] as number | null
      const bv = b[sortKey] as number | null
      // Nulls always sink regardless of direction.
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      return (av - bv) * sortDir
    })
    return copy
  }, [peers, sortKey, sortDir])

  const clickCol = (k: keyof PeerRow) => {
    if (sortKey === k) setSortDir((d) => -d)
    else {
      setSortKey(k)
      setSortDir(k === "company_name" ? 1 : -1)
    }
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[460px] border-collapse">
        <thead>
          <tr>
            {COLS.map(([k, label]) => (
              <th
                key={k}
                scope="col"
                aria-sort={sortKey === k ? (sortDir < 0 ? "descending" : "ascending") : "none"}
                onClick={() => clickCol(k)}
                className={`cursor-pointer whitespace-nowrap border-b border-border/70 px-2 py-[7px] text-[12px] font-medium text-caption ${
                  k === "company_name" ? "text-left" : "text-right"
                }`}
              >
                {label}
                {sortKey === k ? (sortDir < 0 ? " ▾" : " ▴") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr
              key={p.ticker}
              onMouseEnter={() => onHover(p.ticker)}
              onMouseLeave={() => onHover(null)}
              className={`border-t border-border/50 transition-colors ${
                p.is_main ? "bg-tone-info-bg" : hoverPeer === p.ticker ? "bg-raised" : ""
              }`}
            >
              {COLS.map(([k]) => {
                const isMos = k === "mos_pct"
                const mosVal = p.mos_pct
                const mosColor =
                  isMos && mosVal != null
                    ? mosVal >= 0
                      ? "text-success"
                      : "text-warning"
                    : "text-ink"
                return (
                  <td
                    key={k}
                    className={`whitespace-nowrap px-2 py-[7px] text-[12.5px] ${
                      k === "company_name"
                        ? "text-left font-medium text-ink"
                        : `num text-right ${isMos ? `font-medium ${mosColor}` : "text-ink"}`
                    }`}
                  >
                    {k === "company_name" && p.ticker === mainTicker && (
                      <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-tone-info-fg align-middle" />
                    )}
                    {fmtCell(k, p)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ================================================================== */
/*  Value × quality quadrant (P/B × ROE, bubble = market cap)         */
/* ================================================================== */

const QX0 = 50
const QX1 = 548
const QY0 = 20
const QY1 = 180

function ValueQualityQuadrant({ peers, hoverPeer }: { peers: PeerRow[]; hoverPeer: string | null }) {
  const bubbles = useMemo(() => {
    // Only peers with both axes present can be plotted honestly.
    const plot = peers.filter(
      (p) => p.pb_ratio != null && Number.isFinite(p.pb_ratio) && p.roe_pct != null && Number.isFinite(p.roe_pct),
    )
    if (plot.length === 0) return []

    const pbs = plot.map((p) => p.pb_ratio as number)
    const roes = plot.map((p) => p.roe_pct as number)
    const caps = plot.map((p) => (p.market_cap_cr && p.market_cap_cr > 0 ? p.market_cap_cr : 0))
    const pbMin = Math.min(...pbs)
    const pbMax = Math.max(...pbs)
    const roeMin = Math.min(...roes)
    const roeMax = Math.max(...roes)
    const capMax = Math.max(...caps, 1)

    const spanX = pbMax - pbMin || 1
    const spanY = roeMax - roeMin || 1
    // 8% inner padding so bubbles never clip the axes.
    const padX = (QX1 - QX0) * 0.08
    const padY = (QY1 - QY0) * 0.08

    return plot.map((p) => {
      const pb = p.pb_ratio as number
      const roe = p.roe_pct as number
      const cx = QX0 + padX + ((pb - pbMin) / spanX) * (QX1 - QX0 - 2 * padX)
      const cy = QY1 - padY - ((roe - roeMin) / spanY) * (QY1 - QY0 - 2 * padY)
      const cap = p.market_cap_cr && p.market_cap_cr > 0 ? p.market_cap_cr : 0
      // Bubble radius scaled by sqrt(cap) so area ~ market cap.
      const r = 7 + Math.sqrt(cap / capMax) * 11
      const tip = `${shortName(p.company_name, p.ticker)} · ${pb.toFixed(1)}x P/B · ${roe.toFixed(1)}% ROE${
        p.mos_pct != null ? ` · ${p.mos_pct >= 0 ? "+" : ""}${p.mos_pct.toFixed(0)}% vs FV` : ""
      }`
      return {
        ticker: p.ticker,
        short: shortName(p.company_name, p.ticker),
        cx,
        cy,
        r,
        me: p.is_main,
        tip,
      }
    })
  }, [peers])

  if (bubbles.length === 0) {
    return <Muted>Not enough P/B and ROE data across the cohort to plot the map.</Muted>
  }

  return (
    <svg
      viewBox="0 0 560 206"
      width="100%"
      className="block"
      role="img"
      aria-label="Value versus quality map: price-to-book on the horizontal axis, return on equity on the vertical, bubble size by market cap."
    >
      {/* better value · higher quality quadrant tint (lower-left) */}
      <rect x={QX0} y={(QY0 + QY1) / 2} width={(QX1 - QX0) / 2} height={(QY1 - QY0) / 2} fill="rgba(29,158,117,0.08)" />
      <text x={QX0 + 8} y={(QY0 + QY1) / 2 + 14} fontSize={10} fill={DEMO_COLORS.tealDark}>
        Better value · higher quality
      </text>
      <line x1={QX0} y1={QY1} x2={QX1} y2={QY1} stroke={TOKENS.border} />
      <line x1={QX0} y1={QY0} x2={QX0} y2={QY1} stroke={TOKENS.border} />
      <line
        x1={(QX0 + QX1) / 2}
        y1={QY0}
        x2={(QX0 + QX1) / 2}
        y2={QY1}
        stroke={TOKENS.border}
        strokeDasharray="4 3"
      />
      <line
        x1={QX0}
        y1={(QY0 + QY1) / 2}
        x2={QX1}
        y2={(QY0 + QY1) / 2}
        stroke={TOKENS.border}
        strokeDasharray="4 3"
      />
      <text x={(QX0 + QX1) / 2} y={QY1 + 20} textAnchor="middle" fontSize={10} fill={TOKENS.caption}>
        ← lower P/B (better value)&nbsp;&nbsp;&nbsp;&nbsp;higher P/B →
      </text>
      <text
        x={13}
        y={(QY0 + QY1) / 2}
        textAnchor="middle"
        fontSize={10}
        fill={TOKENS.caption}
        transform={`rotate(-90 13 ${(QY0 + QY1) / 2})`}
      >
        higher ROE ↑
      </text>
      {bubbles.map((b) => (
        <g key={b.ticker}>
          <circle
            cx={b.cx}
            cy={b.cy}
            r={b.r}
            fill={b.me ? DEMO_COLORS.teal : DEMO_COLORS.gray}
            opacity={b.me ? 0.78 : 0.5}
            stroke={hoverPeer === b.ticker ? TOKENS.ink : "none"}
            strokeWidth={hoverPeer === b.ticker ? 2.5 : 0}
          >
            <title>{b.tip}</title>
          </circle>
          <text
            x={b.cx}
            y={b.cy + b.r + 11}
            textAnchor="middle"
            fontSize={10}
            fontWeight={b.me ? 500 : 400}
            fill={b.me ? DEMO_COLORS.tealDark : TOKENS.caption}
          >
            {b.short}
          </text>
        </g>
      ))}
    </svg>
  )
}

/* ================================================================== */
/*  Fair-value-vs-price history (jagged, scrubber, pennant flags)     */
/* ================================================================== */

const HpL = 44
const HpRX = 666
const HpT = 16
const HpBY = 262

function HistoryChart({
  ticker,
  points,
  annotations,
}: {
  ticker: string
  points: FVHistoryPoint[]
  annotations: FairValueAnnotation[]
}) {
  const reduced = useReducedMotion()
  const pxRef = useRef<SVGPolylineElement | null>(null)
  const [scrub, setScrub] = useState<number | null>(null)
  const [flagNote, setFlagNote] = useState<number | null>(null)

  const n = points.length

  // Shared value range across both series (price + fair value) so they
  // sit on one honest axis.
  const geom = useMemo(() => {
    const prices = points.map((p) => p.price)
    const fvs = points.map((p) => p.fair_value)
    const all = [...prices, ...fvs].filter((v) => Number.isFinite(v))
    const lo = Math.min(...all)
    const hi = Math.max(...all)
    const span = hi - lo || 1
    const pad = span * 0.08
    const yLo = lo - pad
    const yHi = hi + pad
    const mx = (i: number) => HpL + (i / (n - 1)) * (HpRX - HpL)
    const my = (v: number) => HpT + ((yHi - v) / (yHi - yLo)) * (HpBY - HpT)
    // Three evenly spaced gridlines across the value range.
    const grid = [0.85, 0.5, 0.15].map((f) => {
      const v = yLo + f * (yHi - yLo)
      return { v, y: my(v) }
    })
    return { mx, my, grid }
  }, [points, n])

  const { mx, my, grid } = geom
  const pxPts = points.map((p, i) => `${mx(i).toFixed(1)},${my(p.price).toFixed(1)}`).join(" ")
  const fvPts = points.map((p, i) => `${mx(i).toFixed(1)},${my(p.fair_value).toFixed(1)}`).join(" ")
  const areaPts = `${pxPts} ${mx(n - 1).toFixed(1)},${HpBY} ${mx(0).toFixed(1)},${HpBY}`

  // Month tick labels at 0/¼/½/¾/end.
  const tickIdx = [0, Math.round((n - 1) * 0.25), Math.round((n - 1) * 0.5), Math.round((n - 1) * 0.75), n - 1]

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const i = Math.max(0, Math.min(n - 1, Math.round(((e.clientX - r.left) / r.width) * (n - 1))))
    setScrub(i)
  }

  const si = scrub
  const sPoint = si !== null ? points[si] : null
  const sx = si !== null ? mx(si) : 0
  const syF = sPoint ? my(sPoint.fair_value) : 0
  const syP = sPoint ? my(sPoint.price) : 0
  const tx = si !== null ? Math.max(HpL, Math.min(sx - 106, HpRX - 98)) : 0

  // Map each annotation date to the nearest plotted index for the flag x.
  const flags = useMemo(() => {
    return annotations
      .map((a) => {
        let idx = 0
        for (let i = 0; i < n; i++) {
          if (points[i].date <= a.date) idx = i
          else break
        }
        return { ann: a, idx }
      })
      .filter((f) => f.idx > 0 && f.idx < n - 0.5)
  }, [annotations, points, n])

  const fmtFv = (v: number) => formatCurrency(Math.round(v), undefined, ticker)

  return (
    <div>
      <svg
        viewBox="0 0 720 300"
        width="100%"
        className="block cursor-crosshair"
        role="img"
        aria-label="Price versus fair value over the available window, with model-change flags."
        onMouseMove={onMove}
        onMouseLeave={() => setScrub(null)}
      >
        <defs>
          <linearGradient id="v2PxGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={DEMO_COLORS.teal} stopOpacity={0.16} />
            <stop offset="100%" stopColor={DEMO_COLORS.teal} stopOpacity={0} />
          </linearGradient>
        </defs>

        {grid.map((g) => (
          <g key={g.y}>
            <line x1={HpL} y1={g.y} x2={HpRX} y2={g.y} stroke={TOKENS.border} strokeDasharray="2 5" />
            <text x={672} y={g.y + 3} fontSize={10} fill={TOKENS.caption} className="num">
              {formatCompactCount(g.v)}
            </text>
          </g>
        ))}

        {tickIdx.map((idx) => (
          <text key={idx} x={mx(idx).toFixed(1)} y={284} textAnchor="middle" fontSize={10} fill={TOKENS.caption}>
            {fmtMonth(points[idx].date)}
          </text>
        ))}

        {/* airy under-fade, then dashed FV, then the JAGGED price line */}
        <polygon points={areaPts} fill="url(#v2PxGrad)" />
        <polyline points={fvPts} fill="none" stroke={DEMO_COLORS.gray} strokeWidth={1.4} strokeDasharray="6 5" />
        <polyline
          ref={pxRef}
          points={pxPts}
          fill="none"
          stroke={DEMO_COLORS.teal}
          strokeWidth={1.6}
          strokeLinejoin="round"
        />

        {/* model-change pennant flags — stamped where they happened */}
        {flags.map((f, i) => {
          const x = mx(f.idx)
          const latest = i === flags.length - 1
          return (
            <g
              key={f.ann.date}
              style={{ cursor: "pointer" }}
              role="button"
              tabIndex={0}
              aria-label={`Model change — ${f.ann.cause_label}, ${fmtMonth(f.ann.date)}`}
              onClick={() => setFlagNote(flagNote === i ? null : i)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  setFlagNote(flagNote === i ? null : i)
                }
              }}
            >
              <line
                x1={x}
                x2={x}
                y1={HpT}
                y2={HpBY}
                stroke={DEMO_COLORS.purple}
                strokeWidth={latest ? 1.8 : 1.2}
                strokeDasharray="3 3"
              />
              <line x1={x} x2={x} y1={HpT - 2} y2={HpT + 10} stroke={DEMO_COLORS.purpleDark} strokeWidth={2} />
              <polygon
                points={`${x},${HpT - 2} ${x + (latest ? -13 : 13)},${HpT + 2.5} ${x},${HpT + 7}`}
                fill={latest ? DEMO_COLORS.purple : DEMO_COLORS.purpleLight}
              />
              <text
                x={latest ? x - 16 : x + 16}
                y={latest ? HpT + 20 : HpT + 8}
                textAnchor={latest ? "end" : "start"}
                fontSize={9.5}
                fontWeight={500}
                fill={DEMO_COLORS.purpleDark}
              >
                {fmtMonth(f.ann.date)}
              </text>
              <title>{`${f.ann.cause_label} — ${fmtMonth(f.ann.date)}`}</title>
            </g>
          )
        })}

        {/* hover scrubber with dual anchored tooltips */}
        {si !== null && sPoint && (
          <g>
            <line x1={sx} x2={sx} y1={HpT} y2={HpBY} stroke={TOKENS.caption} strokeDasharray="3 3" opacity={0.6} />
            <circle cx={sx} cy={syF} r={3.5} fill={DEMO_COLORS.gray} stroke={TOKENS.surface} strokeWidth={1.5} />
            <circle cx={sx} cy={syP} r={4} fill={DEMO_COLORS.teal} stroke={TOKENS.surface} strokeWidth={1.5} />
            <g transform={`translate(${tx},${Math.max(HpT, syF - 50).toFixed(1)})`}>
              <rect width={98} height={46} rx={6} fill={TOKENS.raised} stroke={TOKENS.border} />
              <text x={10} y={15} fontSize={10} fill={TOKENS.caption}>
                Fair value
              </text>
              <text x={10} y={29} fontSize={12.5} fontWeight={500} fill={TOKENS.ink} className="num">
                {fmtFv(sPoint.fair_value)}
              </text>
              <text x={10} y={41} fontSize={10} fill={TOKENS.caption}>
                {fmtMonth(sPoint.date)}
              </text>
            </g>
            <g transform={`translate(${tx},${Math.min(HpBY - 46, syP + 6).toFixed(1)})`}>
              <rect width={98} height={46} rx={6} fill={TOKENS.raised} stroke={TOKENS.border} />
              <text x={10} y={15} fontSize={10} fill={TOKENS.caption}>
                Price
              </text>
              <text x={10} y={29} fontSize={12.5} fontWeight={500} fill={TOKENS.ink} className="num">
                {fmtFv(sPoint.price)}
              </text>
              <text
                x={10}
                y={41}
                fontSize={10}
                fill={sPoint.mos_pct >= 0 ? DEMO_COLORS.tealDark : DEMO_COLORS.coralDark}
                className="num"
              >
                {Math.abs(Math.round(sPoint.mos_pct))}% {sPoint.mos_pct >= 0 ? "below FV" : "above FV"}
              </text>
            </g>
          </g>
        )}
      </svg>

      {flagNote !== null && flags[flagNote] && (
        <div
          className="mt-2 rounded-lg border-l-[3px] bg-raised px-3 py-2 text-[12px] leading-relaxed text-ink"
          style={{ borderLeftColor: DEMO_COLORS.purple }}
        >
          <span className="font-medium">{fmtMonth(flags[flagNote].ann.date)}</span> —{" "}
          {flags[flagNote].ann.cause_label}
          {Number.isFinite(flags[flagNote].ann.fv_delta_pct) && (
            <span className="num ml-1 text-caption">
              ({flags[flagNote].ann.fv_delta_pct >= 0 ? "+" : ""}
              {flags[flagNote].ann.fv_delta_pct.toFixed(1)}% fair value)
            </span>
          )}
        </div>
      )}

      <Legend>
        <span className="inline-flex items-center gap-1.5">
          <Swatch color={DEMO_COLORS.teal} />
          Price
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block w-4 border-t-[1.5px] border-dashed" style={{ borderColor: DEMO_COLORS.gray }} />
          Fair value
        </span>
        {flags.length > 0 && (
          <span className="inline-flex items-center gap-1.5">
            <span
              className="inline-block h-2 w-2"
              style={{ background: DEMO_COLORS.purple, clipPath: "polygon(0 0, 100% 35%, 0 70%)" }}
            />
            Model change — tap a flag for the changelog
          </span>
        )}
      </Legend>
      {reduced && <span className="sr-only">Animations reduced per your system setting.</span>}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Small helpers                                                      */
/* ------------------------------------------------------------------ */

/** ISO date (YYYY-MM-DD) → "Mon 'YY" month label. */
function fmtMonth(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  return `${months[d.getMonth()]} '${String(d.getFullYear()).slice(2)}`
}

function SkeletonBlock({ height, label }: { height: number; label: string }) {
  return (
    <div
      className="flex animate-pulse items-center justify-center rounded-lg border border-border/50 bg-raised"
      style={{ height }}
      role="status"
      aria-live="polite"
    >
      <span className="text-[12px] text-caption">{label}…</span>
    </div>
  )
}
