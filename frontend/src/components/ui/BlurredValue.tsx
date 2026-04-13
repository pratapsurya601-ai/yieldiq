"use client"

import Link from "next/link"
import { cn, formatCurrency } from "@/lib/utils"
import { useAuthStore } from "@/store/authStore"
import type { Tier } from "@/types/api"

interface BlurredValueProps {
  value: number
  currency?: string
  label?: string
  requiredTier?: "starter" | "pro"
}

const TIER_RANK: Record<Tier, number> = { free: 0, starter: 1, pro: 2 }

export default function BlurredValue({ value, currency = "INR", label, requiredTier = "starter" }: BlurredValueProps) {
  const tier = useAuthStore((s) => s.tier)
  const hasAccess = TIER_RANK[tier] >= TIER_RANK[requiredTier]

  if (hasAccess) {
    return (
      <span className="font-semibold text-gray-900">
        {label && <span className="text-xs text-gray-500 mr-1">{label}</span>}
        {formatCurrency(value, currency)}
      </span>
    )
  }

  return (
    <span className="inline-flex items-center gap-1.5">
      {label && <span className="text-xs text-gray-500">{label}</span>}
      <span
        className={cn(
          "select-none blur-sm text-gray-400 font-semibold",
          "pointer-events-none"
        )}
        aria-hidden="true"
      >
        {formatCurrency(value, currency)}
      </span>
      <Link
        href="/account?upgrade=true"
        className="text-xs font-medium text-blue-600 hover:text-blue-700 underline underline-offset-2"
      >
        Unlock
      </Link>
    </span>
  )
}
