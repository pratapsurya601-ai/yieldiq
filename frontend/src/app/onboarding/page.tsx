"use client"
import { useState } from "react"
import { useRouter } from "next/navigation"
import { useSettingsStore } from "@/store/settingsStore"

const STEPS = [
  { title: "Welcome to YieldIQ", subtitle: "Know if a stock is undervalued — in 60 seconds" },
  { title: "What describes you best?", subtitle: "We will tailor the experience to your level" },
  { title: "Pick a stock to start", subtitle: "We will show you what YieldIQ can do" },
]

const INVESTOR_TYPES = [
  { value: "beginner" as const, label: "New to investing", desc: "Show me the basics with Learn Mode on" },
  { value: "intermediate" as const, label: "Some experience", desc: "I know P/E and basic ratios" },
  { value: "advanced" as const, label: "Experienced investor", desc: "Show me the full model — DCF, WACC, Monte Carlo" },
]

const STOCKS = [
  { ticker: "RELIANCE.NS", label: "Reliance" },
  { ticker: "TCS.NS", label: "TCS" },
  { ticker: "HDFCBANK.NS", label: "HDFC Bank" },
  { ticker: "INFY.NS", label: "Infosys" },
  { ticker: "ITC.NS", label: "ITC" },
  { ticker: "SBIN.NS", label: "SBI" },
]

export default function OnboardingPage() {
  const [step, setStep] = useState(0)
  const { setInvestorType, completeOnboarding, toggleLearnMode } = useSettingsStore()
  const router = useRouter()

  const handleInvestorType = (type: "beginner" | "intermediate" | "advanced") => {
    setInvestorType(type)
    if (type === "beginner") toggleLearnMode()
    setStep(2)
  }

  const handleStockPick = (ticker: string) => {
    completeOnboarding()
    router.push(`/analysis/${ticker}`)
  }

  const handleSkip = () => {
    completeOnboarding()
    router.push("/home")
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-gray-50">
      <div className="w-full max-w-sm space-y-8">
        {/* Progress dots */}
        <div className="flex justify-center gap-2">
          {STEPS.map((_, i) => (
            <div key={i} className={`w-2 h-2 rounded-full ${i === step ? "bg-blue-600" : i < step ? "bg-blue-300" : "bg-gray-200"}`} />
          ))}
        </div>

        <div className="text-center">
          <h1 className="text-xl font-bold text-gray-900">{STEPS[step].title}</h1>
          <p className="text-sm text-gray-500 mt-1">{STEPS[step].subtitle}</p>
        </div>

        {step === 0 && (
          <div className="space-y-4">
            <div className="bg-white rounded-2xl border border-gray-100 p-6 text-center space-y-3">
              <div className="text-4xl">&#128200;</div>
              <p className="text-sm text-gray-600 leading-relaxed">
                YieldIQ runs a professional DCF model on any stock and tells you
                if it is trading above or below its estimated fair value.
              </p>
              <p className="text-xs text-gray-400">Free. 5 analyses per day. No credit card.</p>
            </div>
            <button onClick={() => setStep(1)} className="w-full py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition">
              Get started
            </button>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-3">
            {INVESTOR_TYPES.map((t) => (
              <button key={t.value} onClick={() => handleInvestorType(t.value)}
                className="w-full text-left bg-white rounded-xl border border-gray-100 p-4 hover:border-blue-300 transition">
                <p className="font-medium text-gray-900">{t.label}</p>
                <p className="text-xs text-gray-500 mt-0.5">{t.desc}</p>
              </button>
            ))}
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              {STOCKS.map((s) => (
                <button key={s.ticker} onClick={() => handleStockPick(s.ticker)}
                  className="bg-white rounded-xl border border-gray-100 p-4 text-center hover:border-blue-300 transition">
                  <p className="font-medium text-gray-900">{s.label}</p>
                  <p className="text-[10px] text-gray-400">{s.ticker}</p>
                </button>
              ))}
            </div>
            <button onClick={handleSkip} className="w-full py-2 text-sm text-gray-500 hover:text-gray-700">
              Skip for now
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
