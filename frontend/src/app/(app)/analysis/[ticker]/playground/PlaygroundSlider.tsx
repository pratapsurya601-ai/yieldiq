"use client"

import { useState } from "react"
import type { SliderDef } from "./PlaygroundBody"

interface Props {
  def: SliderDef
  value: number
  onChange: (next: number) => void
  locked: boolean
}

export default function PlaygroundSlider({ def, value, onChange, locked }: Props) {
  const [showTip, setShowTip] = useState(false)

  const display = `${(value * 100).toFixed(1)}%`
  const baseDisplay = `${(def.defaultValue * 100).toFixed(1)}%`
  const min = def.min
  const max = def.max

  return (
    <div className={locked ? "opacity-60" : undefined}>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <label
            htmlFor={`slider-${def.key}`}
            className="text-xs font-semibold uppercase tracking-wider text-ink"
          >
            {def.label}
          </label>
          <button
            type="button"
            onClick={() => setShowTip((v) => !v)}
            onBlur={() => setShowTip(false)}
            aria-label={`Explain ${def.label}`}
            className="rounded-full border border-slate-300 px-1.5 text-[10px] font-bold leading-none text-slate-500 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800"
          >
            ?
          </button>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold tabular-nums text-ink">
            {display}
          </span>
          {Math.abs(value - def.defaultValue) > 1e-6 && !locked && (
            <button
              type="button"
              onClick={() => onChange(def.defaultValue)}
              className="text-[10px] font-medium text-slate-500 hover:text-emerald-700 dark:text-slate-400 dark:hover:text-emerald-300"
              aria-label={`Reset ${def.label} to ${baseDisplay}`}
            >
              reset
            </button>
          )}
        </div>
      </div>

      {showTip && (
        <p className="mb-1 rounded-md border border-slate-200 bg-slate-50 p-2 text-[11px] leading-snug text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
          {def.tooltip}
        </p>
      )}

      <input
        id={`slider-${def.key}`}
        type="range"
        min={min}
        max={max}
        step={def.step}
        value={value}
        disabled={locked}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full cursor-pointer appearance-none rounded-full bg-slate-200 accent-emerald-600 dark:bg-slate-700"
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={value}
        aria-valuetext={display}
      />

      <div className="mt-1 flex justify-between font-mono text-[10px] tabular-nums text-muted">
        <span>{(min * 100).toFixed(1)}%</span>
        <span>{(max * 100).toFixed(1)}%</span>
      </div>

      {locked && (
        <p className="mt-1 text-[10px] font-medium text-emerald-700 dark:text-emerald-300">
          Paid feature &middot; <a href="/pricing" className="underline">unlock</a>
        </p>
      )}
    </div>
  )
}
