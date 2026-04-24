"use client"
// TODO: swap to design tokens fully once Agent 1 lands — already using
// text-ink/text-body/bg-surface/border-border where tokens exist.
import Link from "next/link"
import { useAuthStore } from "@/store/authStore"
import { TIER_LIMITS } from "@/lib/constants"
import PersonalHeader from "@/components/home/PersonalHeader"
import TopAction from "@/components/home/TopAction"
import MoversRail from "@/components/home/MoversRail"
import OpportunityRail from "@/components/home/OpportunityRail"
import MarketAccordion from "@/components/home/MarketAccordion"
import ErrorBoundary from "@/components/ErrorBoundary"
import { useEffect, useState } from "react"

export default function HomePage() {
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  const email = useAuthStore((s) => s.email)
  const tier = useAuthStore((s) => s.tier)
  const analysesToday = useAuthStore((s) => s.analysesToday)
  const rawLimit = TIER_LIMITS[tier]
  const dailyLimit = typeof rawLimit === "number" ? rawLimit : null
  const remaining =
    dailyLimit !== null ? Math.max(0, dailyLimit - analysesToday) : null
  const showQuotaWarning =
    tier === "free" && remaining !== null && remaining <= 1

  return (
    <div className="max-w-2xl md:max-w-4xl lg:max-w-5xl mx-auto pb-20 bg-bg">
      {/* Quota warning stays ABOVE the greeting so the "your action"
          flow below is not interrupted mid-scan. */}
      {showQuotaWarning && mounted && (
        <div className="px-4 pt-4">
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-start gap-3">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center">
              <svg
                className="w-4 h-4 text-amber-700"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
                />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-amber-900">
                {remaining === 0
                  ? "You\u2019ve used all 5 analyses today"
                  : "1 analysis left today"}
              </p>
              <p className="text-xs text-amber-800 mt-0.5">
                {remaining === 0
                  ? "Monthly quota resets on the 1st. Upgrade to Analyst for unlimited analyses."
                  : "Make it count \u2014 or upgrade to Analyst for unlimited analyses (\u20B9799/mo)."}
              </p>
            </div>
            <Link
              href="/pricing"
              className="flex-shrink-0 bg-amber-600 text-white text-xs font-semibold px-3 py-1.5 rounded-lg hover:bg-amber-700 active:scale-[0.97] transition min-h-[36px] inline-flex items-center"
            >
              Upgrade
            </Link>
          </div>
        </div>
      )}

      {/* 1. Greeting */}
      <PersonalHeader email={email} />

      {/* 2. Your top action */}
      <div className="px-4 pt-2">
        <TopAction />
      </div>

      {/* Each rail is wrapped in its own ErrorBoundary so a single dying
          rail (e.g. a transient API failure deep inside MarketAccordion's
          fear/greed widget) cannot nuke the entire homepage. Fallbacks
          are deliberately quiet — a neutral card matching the rail's
          shape, never a giant red error block on the user's home screen. */}

      {/* 3. Your movers */}
      <div className="mt-6">
        <ErrorBoundary
          label="MoversRail"
          fallback={
            <section className="px-4">
              <div className="bg-bg rounded-2xl border border-border p-5">
                <p className="text-sm text-body">
                  Movers temporarily unavailable.
                </p>
              </div>
            </section>
          }
        >
          <MoversRail />
        </ErrorBoundary>
      </div>

      {/* 4. Opportunities (curated from YieldIQ 50) */}
      <div className="mt-6">
        <ErrorBoundary
          label="OpportunityRail"
          fallback={
            <section className="px-4">
              <div className="bg-bg rounded-2xl border border-border p-5">
                <p className="text-sm text-body">
                  Top wide-moat stocks — refreshing.
                </p>
              </div>
            </section>
          }
        >
          <OpportunityRail />
        </ErrorBoundary>
      </div>

      {/* 5. Market snapshot — collapsed accordion */}
      <div className="mt-6">
        <ErrorBoundary
          label="MarketAccordion"
          fallback={
            <section className="px-4">
              <div className="bg-bg rounded-2xl border border-border p-5">
                <p className="text-sm text-body">
                  Market snapshot temporarily unavailable.
                </p>
              </div>
            </section>
          }
        >
          <MarketAccordion />
        </ErrorBoundary>
      </div>
    </div>
  )
}
