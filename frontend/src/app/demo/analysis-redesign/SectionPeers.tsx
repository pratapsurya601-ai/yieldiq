"use client"

// L · §8 Peers & track record — sortable peer table cross-highlighting
// the quadrant bubbles on row hover; jagged FV-vs-price history (line
// draws itself, soft under-fade, hover scrubber with dual anchored
// tooltips) stamped with the two model-change pennant flags (04);
// track-record stat tiles. Caption rule: no silent revisions, ever.
import { useEffect, useRef, useState } from "react"
import { CircleCheck } from "lucide-react"

import {
  HIST_MONTHS,
  HIST_N,
  HISTORY,
  MODEL_FLAGS,
  PEER_COLS,
  PEERS,
  QUADRANT_BUBBLES,
  TRACK_STATS,
  type PeerRow,
} from "./data"
import { inr, seg, useStageClock } from "./hooks"
import { DEMO_COLORS, TOKENS } from "./theme"
import { Kpi, Legend, Ribbon, Section, Subh, Swatch } from "./ui"

export default function SectionPeers() {
  const [hoverPeer, setHoverPeer] = useState<string | null>(null)

  return (
    <Section
      id="sec-8"
      num="8"
      title="Peers & track record"
      ribbon={
        <Ribbon tone="good" icon={<CircleCheck size={13} aria-hidden="true" />}>
          High confidence
        </Ribbon>
      }
    >
      <Subh>
        Compare with peers{" "}
        <span className="font-normal text-caption">
          — tap a column to sort, hover a row to find it on the map
        </span>
      </Subh>
      <PeerTable hoverPeer={hoverPeer} onHover={setHoverPeer} />

      <Subh className="mt-5">Value vs quality map</Subh>
      <svg
        viewBox="0 0 560 206"
        width="100%"
        className="block"
        role="img"
        aria-label="Value versus quality quadrant map of five banks."
      >
        <rect x={50} y={20} width={303} height={77.3} fill="rgba(29,158,117,0.08)" />
        <text x={58} y={34} fontSize={10} fill={DEMO_COLORS.tealDark}>
          Better value · higher quality
        </text>
        <line x1={50} y1={180} x2={548} y2={180} stroke={TOKENS.border} />
        <line x1={50} y1={20} x2={50} y2={180} stroke={TOKENS.border} />
        <line x1={353} y1={20} x2={353} y2={180} stroke={TOKENS.border} strokeDasharray="4 3" />
        <line x1={50} y1={97.3} x2={548} y2={97.3} stroke={TOKENS.border} strokeDasharray="4 3" />
        <text x={300} y={200} textAnchor="middle" fontSize={10} fill={TOKENS.caption}>
          ← lower P/B (better value)&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;higher P/B →
        </text>
        <text x={13} y={100} textAnchor="middle" fontSize={10} fill={TOKENS.caption} transform="rotate(-90 13 100)">
          higher ROE ↑
        </text>
        {QUADRANT_BUBBLES.map((b) => (
          <g key={b.t}>
            <circle
              cx={b.cx}
              cy={b.cy}
              r={b.r}
              fill={b.fill}
              opacity={b.opacity}
              stroke={hoverPeer === b.t ? TOKENS.ink : "none"}
              strokeWidth={hoverPeer === b.t ? 2.5 : 0}
            >
              <title>{b.tip}</title>
            </circle>
            <text
              x={b.cx}
              y={b.me ? b.cy + 20.7 : b.t === "ICICIBANK" ? b.cy - 14.7 : b.t === "SBIN" ? b.cy - 19.7 : b.cy + 19}
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

      <Subh className="mt-5">
        Track record — fair value vs price (24 months){" "}
        <span className="font-normal text-caption">— hover the chart</span>
      </Subh>
      <HistoryChart />

      <div className="mt-3.5 grid grid-cols-2 gap-2.5 md:grid-cols-4">
        {TRACK_STATS.map(([label, value]) => (
          <Kpi key={label} label={label} value={<span className="text-[17px]">{value}</span>} />
        ))}
      </div>
    </Section>
  )
}

// --- sortable peer table ----------------------------------------------------
function fmt(k: keyof PeerRow, p: PeerRow): string {
  const v = p[k]
  if (k === "t") return String(v)
  const n = v as number
  if (k === "px") return inr(n)
  if (k === "mos") return `+${n}%`
  if (k === "pb") return n.toFixed(1) + "x"
  if (k === "roe" || k === "dy") return n.toFixed(1) + "%"
  return `₹${n}L cr`
}

function PeerTable({ hoverPeer, onHover }: { hoverPeer: string | null; onHover: (t: string | null) => void }) {
  const [sortKey, setSortKey] = useState<keyof PeerRow>("mos")
  const [sortDir, setSortDir] = useState(-1)

  const rows = [...PEERS].sort((a, b) => {
    if (sortKey === "t") return (a.t < b.t ? -1 : 1) * sortDir
    return ((a[sortKey] as number) - (b[sortKey] as number)) * sortDir
  })

  const clickCol = (k: keyof PeerRow) => {
    if (sortKey === k) setSortDir((d) => -d)
    else {
      setSortKey(k)
      setSortDir(k === "t" ? 1 : -1)
    }
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[430px] border-collapse">
        <thead>
          <tr>
            {PEER_COLS.map(([k, label]) => (
              <th
                key={k}
                onClick={() => clickCol(k)}
                className={`cursor-pointer whitespace-nowrap border-b border-border/70 px-2 py-[7px] text-[12px] font-medium text-caption ${
                  k === "t" ? "text-left" : "text-right"
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
              key={p.t}
              onMouseEnter={() => onHover(p.t)}
              onMouseLeave={() => onHover(null)}
              className={`border-t border-border/50 transition-colors ${
                p.me ? "bg-tone-info-bg" : hoverPeer === p.t ? "bg-raised" : ""
              }`}
            >
              {PEER_COLS.map(([k]) => (
                <td
                  key={k}
                  className={`whitespace-nowrap px-2 py-[7px] text-[12.5px] ${
                    k === "t"
                      ? "text-left font-medium text-ink"
                      : k === "mos"
                        ? "num text-right font-medium text-success"
                        : "num text-right text-ink"
                  }`}
                >
                  {k === "t" && p.me && (
                    <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-tone-info-fg align-middle" />
                  )}
                  {fmt(k, p)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// --- FV vs price history with scrubber + model-change pennant flags ---------
const pL = 44
const pRX = 666
const pT = 16
const pBY = 262
const mx = (i: number) => pL + (i / (HIST_N - 1)) * (pRX - pL)
const my = (v: number) => pT + ((2120 - v) / 720) * (pBY - pT)

function HistoryChart() {
  const { ref, elapsed, reduced } = useStageClock(3200, 0.25)
  const pxRef = useRef<SVGPolylineElement | null>(null)
  const [pxLen, setPxLen] = useState<number | null>(null)
  const [scrub, setScrub] = useState<number | null>(null)
  const [flagNote, setFlagNote] = useState<number | null>(null)

  useEffect(() => {
    if (pxRef.current) setPxLen(pxRef.current.getTotalLength())
  }, [])

  const pxPts = HISTORY.px.map((v, i) => `${mx(i).toFixed(1)},${my(v).toFixed(1)}`).join(" ")
  const fvPts = HISTORY.fv.map((v, i) => `${mx(i).toFixed(1)},${my(v).toFixed(1)}`).join(" ")
  const areaPts = `${pxPts} ${mx(HIST_N - 1).toFixed(1)},${pBY} ${mx(0).toFixed(1)},${pBY}`

  const draw = seg(elapsed, 0, 1700)
  const dashOffset = pxLen !== null && !reduced ? pxLen * (1 - draw) : 0

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const i = Math.max(0, Math.min(HIST_N - 1, Math.round(((e.clientX - r.left) / r.width) * (HIST_N - 1))))
    setScrub(i)
  }

  const si = scrub
  const sx = si !== null ? mx(si) : 0
  const syF = si !== null ? my(HISTORY.fv[si]) : 0
  const syP = si !== null ? my(HISTORY.px[si]) : 0
  const sMos = si !== null ? Math.round(((HISTORY.fv[si] - HISTORY.px[si]) / HISTORY.fv[si]) * 100) : 0
  const tx = si !== null ? Math.max(pL, Math.min(sx - 106, pRX - 98)) : 0

  return (
    <div ref={ref}>
      <svg
        viewBox="0 0 720 300"
        width="100%"
        className="block cursor-crosshair"
        role="img"
        aria-label="Price versus fair value over 24 months with two model-change flags."
        onMouseMove={onMove}
        onMouseLeave={() => setScrub(null)}
      >
        <defs>
          <linearGradient id="demoPxGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={DEMO_COLORS.teal} stopOpacity={0.16} />
            <stop offset="100%" stopColor={DEMO_COLORS.teal} stopOpacity={0} />
          </linearGradient>
        </defs>
        {(
          [
            [2100, "2,100"],
            [1800, "1,800"],
            [1500, "1,500"],
          ] as const
        ).map(([v, label]) => (
          <g key={v}>
            <line x1={pL} y1={my(v)} x2={pRX} y2={my(v)} stroke={TOKENS.border} strokeDasharray="2 5" />
            <text x={672} y={my(v) + 3} fontSize={10} fill={TOKENS.caption} className="num">
              {label}
            </text>
          </g>
        ))}
        {[0, 6, 12, 18, 24].map((m) => (
          <text
            key={m}
            x={mx(Math.round((m / 24) * (HIST_N - 1))).toFixed(1)}
            y={284}
            textAnchor="middle"
            fontSize={10}
            fill={TOKENS.caption}
          >
            {HIST_MONTHS[m]}
          </text>
        ))}
        {/* soft under-fade, then dashed FV, then the jagged price line */}
        <polygon points={areaPts} fill="url(#demoPxGrad)" opacity={seg(elapsed, 600, 1000)} />
        <polyline
          points={fvPts}
          fill="none"
          stroke={DEMO_COLORS.gray}
          strokeWidth={1.4}
          strokeDasharray="6 5"
          opacity={seg(elapsed, 0, 1100)}
        />
        <polyline
          ref={pxRef}
          points={pxPts}
          fill="none"
          stroke={DEMO_COLORS.teal}
          strokeWidth={1.6}
          strokeLinejoin="round"
          strokeDasharray={pxLen !== null && !reduced ? pxLen : undefined}
          strokeDashoffset={dashOffset}
        />

        {/* model-change pennant flags (04) — stamped where they happened */}
        {MODEL_FLAGS.map((f, i) => {
          const x = pL + f.frac * (pRX - pL)
          const on = elapsed >= 1700 + i * 350
          return (
            <g
              key={f.date}
              opacity={on ? 1 : 0}
              style={{ transition: "opacity .5s", cursor: "pointer" }}
              role="button"
              tabIndex={0}
              aria-label={`Model change — ${f.title}, ${f.date}`}
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
                y1={pT}
                y2={pBY}
                stroke={DEMO_COLORS.purple}
                strokeWidth={f.latest ? 1.8 : 1.2}
                strokeDasharray="3 3"
              />
              <line x1={x} x2={x} y1={pT - 2} y2={pT + 10} stroke={DEMO_COLORS.purpleDark} strokeWidth={2} />
              <polygon
                points={`${x},${pT - 2} ${x + (f.latest ? -13 : 13)},${pT + 2.5} ${x},${pT + 7}`}
                fill={f.latest ? DEMO_COLORS.purple : DEMO_COLORS.purpleLight}
              />
              <text
                x={f.latest ? x - 16 : x + 16}
                y={f.latest ? pT + 20 : pT + 8}
                textAnchor={f.latest ? "end" : "start"}
                fontSize={9.5}
                fontWeight={500}
                fill={DEMO_COLORS.purpleDark}
              >
                {f.date}
              </text>
              <title>{`${f.title} — ${f.date}`}</title>
            </g>
          )
        })}

        {/* hover scrubber with dual anchored tooltips */}
        {si !== null && (
          <g>
            <line x1={sx} x2={sx} y1={pT} y2={pBY} stroke={TOKENS.caption} strokeDasharray="3 3" opacity={0.6} />
            <circle cx={sx} cy={syF} r={3.5} fill={DEMO_COLORS.gray} stroke={TOKENS.surface} strokeWidth={1.5} />
            <circle cx={sx} cy={syP} r={4} fill={DEMO_COLORS.teal} stroke={TOKENS.surface} strokeWidth={1.5} />
            <g transform={`translate(${tx},${Math.max(pT, syF - 50).toFixed(1)})`}>
              <rect width={98} height={46} rx={6} fill={TOKENS.raised} stroke={TOKENS.border} />
              <text x={10} y={15} fontSize={10} fill={TOKENS.caption}>
                Fair value
              </text>
              <text x={10} y={29} fontSize={12.5} fontWeight={500} fill={TOKENS.ink} className="num">
                {inr(HISTORY.fv[si])}
              </text>
              <text x={10} y={41} fontSize={10} fill={TOKENS.caption}>
                {HIST_MONTHS[Math.round((si / (HIST_N - 1)) * 24)]}
              </text>
            </g>
            <g transform={`translate(${tx},${Math.min(pBY - 46, syP + 6).toFixed(1)})`}>
              <rect width={98} height={46} rx={6} fill={TOKENS.raised} stroke={TOKENS.border} />
              <text x={10} y={15} fontSize={10} fill={TOKENS.caption}>
                Price
              </text>
              <text x={10} y={29} fontSize={12.5} fontWeight={500} fill={TOKENS.ink} className="num">
                {inr(HISTORY.px[si])}
              </text>
              <text x={10} y={41} fontSize={10} fill={DEMO_COLORS.tealDark} className="num">
                {sMos}% below FV
              </text>
            </g>
          </g>
        )}
      </svg>

      {flagNote !== null && (
        <div className="mt-2 rounded-lg border-l-[3px] bg-raised px-3 py-2 text-[12px] leading-relaxed text-ink" style={{ borderLeftColor: DEMO_COLORS.purple }}>
          <span className="font-medium">{MODEL_FLAGS[flagNote].date}</span> —{" "}
          {MODEL_FLAGS[flagNote].changelog}
        </div>
      )}

      <Legend>
        <span className="inline-flex items-center gap-1.5">
          <Swatch color={DEMO_COLORS.teal} />
          Price — green below fair value
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block w-4 border-t-[1.5px] border-dashed" style={{ borderColor: DEMO_COLORS.gray }} />
          Fair value
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2" style={{ background: DEMO_COLORS.purple, clipPath: "polygon(0 0, 100% 35%, 0 70%)" }} />
          Model change — tap a flag for the changelog. No silent revisions, ever.
        </span>
      </Legend>
    </div>
  )
}
