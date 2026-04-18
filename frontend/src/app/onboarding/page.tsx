"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import OnboardingStepper from "@/components/onboarding/OnboardingStepper"
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

type StepIndex = 0 | 1 | 2

/**
 * Three-screen onboarding: Interests → First stock (Prism aha) → Explainer.
 * Skippable at every stage. Persists to localStorage via `onboardingPreferences`
 * and also marks the existing settingsStore `onboardingComplete` flag so the
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

  const handleInterestsContinue = useCallback((selected: InterestKey[]) => {
    writePreferences({ interests: selected })
    setStep(1)
  }, [])

  const handleFirstStockNext = useCallback((prism: PrismData | null) => {
    if (prism) {
      setPrismReference(prism)
      writePreferences({ firstStock: prism.ticker })
    }
    setStep(2)
  }, [])

  const handleFinish = useCallback(() => {
    finish({ firstStock: prismReference?.ticker ?? null })
  }, [finish, prismReference])

  // Don't render anything until we've checked localStorage — prevents a
  // flash of the onboarding UI for users who already finished it.
  const content = useMemo(() => {
    if (!mounted) return null
    if (step === 0) {
      return (
        <StepInterests
          initial={initialInterests}
          onContinue={handleInterestsContinue}
        />
      )
    }
    if (step === 1) {
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
    handleInterestsContinue,
    handleFirstStockNext,
    handleFinish,
  ])

  return (
    <div className="min-h-screen bg-bg text-ink">
      <div className="max-w-md mx-auto">
        <OnboardingStepper
          step={step}
          onSkip={handleSkip}
          showSkip={step !== 2}
        />
        {content}
      </div>
    </div>
  )
}
