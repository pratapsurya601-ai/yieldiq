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
        "relative rounded-xl bg-gradient-to-br from-blue-50/60 to-white border border-gray-100 shadow-sm overflow-hidden",
        "p-4"
      )}
    >
      {/* Shimmer/glow left border */}
      <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-blue-400 via-blue-600 to-blue-400" />

      <div className="pl-3">
        <div className="flex items-start justify-between mb-2">
          <div>
            <h3 className="text-base font-bold text-gray-900">{ticker}</h3>
            <p className="text-xs text-gray-500">{companyName}</p>
          </div>
          <div
            className="flex items-center justify-center h-12 w-12 rounded-full font-bold text-base text-white shadow-md"
            style={{ backgroundColor: SCORE_COLOR(score) }}
          >
            {score}
          </div>
        </div>

        <div className="flex gap-3 mb-3">
          <span className="text-xs text-gray-500">
            MoS: <span className="font-medium text-gray-700">{formatMoS(mos)}</span>
          </span>
          <span className="text-xs text-gray-500">
            Moat: <span className="font-medium text-gray-700">{moat}</span>
          </span>
        </div>

        <p className="text-sm text-gray-600 line-clamp-2 mb-3">{summary}</p>

        <div className="flex items-center justify-between">
          <Link
            href={`/analysis/${ticker}`}
            className={cn(
              "inline-flex items-center rounded-lg px-4 py-2 text-sm font-medium",
              "bg-blue-600 text-white hover:bg-blue-700 active:bg-blue-800",
              "transition-colors"
            )}
          >
            Analyse
          </Link>
          <span className="text-[10px] text-gray-400">Updated today</span>
        </div>
      </div>
    </div>
  )
}
