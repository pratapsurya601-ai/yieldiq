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
        "rounded-xl bg-white border border-gray-100 shadow-sm",
        "border-l-4 border-l-blue-600 p-4"
      )}
    >
      <div className="flex items-start justify-between mb-2">
        <div>
          <h3 className="text-base font-bold text-gray-900">{ticker}</h3>
          <p className="text-xs text-gray-500">{companyName}</p>
        </div>
        <div
          className="flex items-center justify-center h-10 w-10 rounded-full font-bold text-sm text-white"
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
    </div>
  )
}
