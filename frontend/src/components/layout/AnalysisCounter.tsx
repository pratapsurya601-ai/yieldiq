"use client"

import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/authStore"
import { TIER_LIMITS } from "@/lib/constants"

export default function AnalysisCounter() {
  const analysesToday = useAuthStore((s) => s.analysesToday)
  const tier = useAuthStore((s) => s.tier)
  const limit = TIER_LIMITS[tier]

  if (tier !== "free") return null

  const pct = Math.min((analysesToday / (limit as number)) * 100, 100)
  const isNearLimit = analysesToday >= (limit as number) - 1

  return (
    <div className="px-4 py-1.5">
      <div className="flex items-center justify-between mb-1">
        <span
          className={cn(
            "text-[10px] font-medium",
            isNearLimit ? "text-amber-600" : "text-gray-500"
          )}
        >
          {analysesToday}/{limit} analyses today
        </span>
      </div>
      <div className="h-1 w-full rounded-full bg-gray-200 overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500",
            isNearLimit ? "bg-amber-500" : "bg-blue-500"
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
