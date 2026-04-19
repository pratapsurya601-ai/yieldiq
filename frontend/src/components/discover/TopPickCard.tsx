"use client"

import Link from "next/link"
import { cn, formatMoS } from "@/lib/utils"
import { SCORE_COLOR } from "@/lib/constants"
import type { MoatGrade } from "@/types/api"

interface TopPickCardProps {
  ticker: string
  companyName: string
  score: number
  mos: number
  moat: MoatGrade
  summary: string
}

export default function TopPickCard({ ticker, companyName, score, mos, moat, summary }: TopPickCardProps) {
  return (
    <div
      className={cn(
        "relative rounded-xl bg-gradient-to-br from-brand-50/60 to-surface border border-border shadow-sm overflow-hidden",
        "p-4"
      )}
    >
      {/* Shimmer/glow left border */}
      <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-blue-400 via-blue-600 to-blue-400" />

      <div className="pl-3">
        <div className="flex items-start justify-between mb-2">
          <div>
            <h3 className="text-base font-bold text-ink">{ticker}</h3>
            <p className="text-xs text-caption">{companyName}</p>
          </div>
          <div
            className="flex items-center justify-center h-12 w-12 rounded-full font-bold text-base text-white shadow-md"
            style={{ backgroundColor: SCORE_COLOR(score) }}
          >
            {score}
          </div>
        </div>

        <div className="flex gap-3 mb-3">
          <span className="text-xs text-caption">
            MoS: <span className="font-medium text-body">{formatMoS(mos)}</span>
          </span>
          <span className="text-xs text-caption">
            Moat: <span className="font-medium text-body">{moat}</span>
          </span>
        </div>

        <p className="text-sm text-body line-clamp-2 mb-3">{summary}</p>

        <div className="flex items-center justify-between">
          <Link
            href={`/analysis/${ticker}`}
            className={cn(
              "inline-flex items-center rounded-lg px-4 py-2 text-sm font-medium",
              "bg-brand text-white hover:opacity-90 active:opacity-80",
              "transition-colors"
            )}
          >
            Analyse
          </Link>
          <span className="text-[10px] text-caption">Updated today</span>
        </div>
      </div>
    </div>
  )
}
