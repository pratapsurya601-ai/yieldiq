"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import OnboardingStepper from "@/components/onboarding/OnboardingStepper"
import StepName from "@/components/onboarding/StepName"
import StepInterests from "@/components/onboarding/StepInterests"
import StepFirstStock from "@/components/onboarding/StepFirstStock"
import StepExplainer from "@/components/onboarding/StepExplainer"
import {
  isOnboardingComplete,
  markCompleted,
  readPreferences,
  writePreferences,
  type InterestKey,
} from "@/lib/onboardingPreferences"
import { useSettingsStore } from "@/store/settingsStore"
import type { PrismData } from "@/components/prism/types"

// Four-screen onboarding: Name → Interests → First stock → Explainer.
// StepName was added in PR #72 — it captures the editable display name
// and persists via PATCH /api/v1/account/profile before advancing.
type StepIndex = 0 | 1 | 2 | 3

const TOTAL_STEPS = 4

/**
 * Onboarding orchestrator. Skippable from any non-terminal step except
 * Name (skipping the name leaves the greeting on the email-derived
 * fallback, which is the existing behaviour pre-#72 — so Skip on Name
 * is also allowed and just doesn't write anything).
 *
 * Persists interests/firstStock to localStorage via `onboardingPreferences`
 * and marks the existing settingsStore `onboardingComplete` flag so the
 * auth redirect logic elsewhere stays in sync.
 */
export default function OnboardingPage() {
  const router = useRouter()
  const completeOnboardingStore = useSettingsStore((s) => s.completeOnboarding)

  const [mounted, setMounted] = useState(false)
  const [step, setStep] = useState<StepIndex>(0)
  const [initialInterests, setInitialInterests] = useState<InterestKey[]>([])
  const [prismReference, setPrismReference] = useState<PrismData | null>(null)

  useEffect(() => {
    setMounted(true)
    const prefs = readPreferences()
    setInitialInterests(prefs.interests)
    if (prefs.completed || isOnboardingComplete()) {
      router.replace("/home")
    }
  }, [router])

  const finish = useCallback(
    (extra: Parameters<typeof markCompleted>[0] = {}) => {
      markCompleted(extra)
      completeOnboardingStore()
      router.replace("/home")
    },
    [completeOnboardingStore, router],
  )

  const handleSkip = useCallback(() => finish(), [finish])

  const handleNameContinue = useCallback(() => {
    setStep(1)
  }, [])

  const handleInterestsContinue = useCallback((selected: InterestKey[]) => {
    writePreferences({ interests: selected })
    setStep(2)
  }, [])

  const handleFirstStockNext = useCallback((prism: PrismData | null) => {
    if (prism) {
      setPrismReference(prism)
      writePreferences({ firstStock: prism.ticker })
    }
    setStep(3)
  }, [])

  const handleFinish = useCallback(() => {
    finish({ firstStock: prismReference?.ticker ?? null })
  }, [finish, prismReference])

  // Don't render anything until we've checked localStorage — prevents a
  // flash of the onboarding UI for users who already finished it.
  const content = useMemo(() => {
    if (!mounted) return null
    if (step === 0) {
      return <StepName onContinue={handleNameContinue} />
    }
    if (step === 1) {
      return (
        <StepInterests
          initial={initialInterests}
          onContinue={handleInterestsContinue}
        />
      )
    }
    if (step === 2) {
      return <StepFirstStock onNext={handleFirstStockNext} />
    }
    return (
      <StepExplainer referenceData={prismReference} onFinish={handleFinish} />
    )
  }, [
    mounted,
    step,
    initialInterests,
    prismReference,
    handleNameContinue,
    handleInterestsContinue,
    handleFirstStockNext,
    handleFinish,
  ])

  // Stepper expects step: 0 | 1 | 2 in its existing union; with 4 total
  // steps we widen the prop locally — Stepper renders by index against
  // totalSteps regardless of the union, so the cast is safe.
  return (
    <div className="min-h-screen bg-bg text-ink">
      <div className="max-w-md mx-auto">
        <OnboardingStepper
          step={step}
          totalSteps={TOTAL_STEPS}
          onSkip={handleSkip}
          showSkip={step !== 3}
        />
        {content}
      </div>
    </div>
  )
}
