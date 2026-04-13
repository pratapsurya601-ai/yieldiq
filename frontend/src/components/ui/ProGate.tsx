"use client"

import Link from "next/link"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/authStore"
import type { Tier } from "@/types/api"

interface ProGateProps {
  children: React.ReactNode
  requiredTier?: "starter" | "pro"
  feature?: string
}

const TIER_RANK: Record<Tier, number> = { free: 0, starter: 1, pro: 2 }

export default function ProGate({ children, requiredTier = "starter", feature }: ProGateProps) {
  const tier = useAuthStore((s) => s.tier)
  const hasAccess = TIER_RANK[tier] >= TIER_RANK[requiredTier]

  if (hasAccess) {
    return <>{children}</>
  }

  return (
    <div className={cn("relative rounded-xl overflow-hidden")}>
      {/* Blurred content preview */}
      <div className="pointer-events-none select-none blur-sm opacity-50" aria-hidden="true">
        {children}
      </div>

      {/* Upgrade overlay */}
      <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/70 backdrop-blur-sm rounded-xl">
        <div className="flex flex-col items-center gap-3 px-6 text-center">
          <div className="h-10 w-10 rounded-full bg-blue-50 flex items-center justify-center">
            <svg className="h-5 w-5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
            </svg>
          </div>
          <p className="text-sm font-medium text-gray-900">
            {feature ? `${feature} requires` : "This feature requires"}{" "}
            {requiredTier === "pro" ? "Pro" : "Starter"} plan
          </p>
          <Link
            href="/account?upgrade=true"
            className={cn(
              "inline-flex items-center rounded-full px-5 py-2 text-sm font-medium",
              "bg-blue-600 text-white hover:bg-blue-700 transition-colors"
            )}
          >
            Upgrade now
          </Link>
        </div>
      </div>
    </div>
  )
}
