"use client"

interface OnboardingStepperProps {
  step: 0 | 1 | 2
  totalSteps?: number
  onSkip?: () => void
  showSkip?: boolean
}

/**
 * Top-of-screen progress dots + Skip link.
 * Skip is a plain text link (top-right) so users never feel trapped.
 */
export default function OnboardingStepper({
  step,
  totalSteps = 3,
  onSkip,
  showSkip = true,
}: OnboardingStepperProps) {
  return (
    <div className="flex items-center justify-between pt-4 px-4 min-h-[44px]">
      <div
        className="flex items-center gap-1.5"
        role="progressbar"
        aria-valuemin={1}
        aria-valuemax={totalSteps}
        aria-valuenow={step + 1}
        aria-label={`Step ${step + 1} of ${totalSteps}`}
      >
        {Array.from({ length: totalSteps }).map((_, i) => (
          <span
            key={i}
            aria-hidden="true"
            className={
              i === step
                ? "h-1.5 w-6 rounded-full bg-brand transition-all duration-300"
                : i < step
                  ? "h-1.5 w-1.5 rounded-full bg-brand/50 transition-all duration-300"
                  : "h-1.5 w-1.5 rounded-full bg-border transition-all duration-300"
            }
          />
        ))}
      </div>
      {showSkip && onSkip ? (
        <button
          type="button"
          onClick={onSkip}
          className="min-h-[44px] px-3 text-sm text-caption hover:text-ink transition-colors"
          aria-label="Skip onboarding"
        >
          Skip
        </button>
      ) : (
        <span className="min-h-[44px] w-[44px]" aria-hidden="true" />
      )}
    </div>
  )
}
