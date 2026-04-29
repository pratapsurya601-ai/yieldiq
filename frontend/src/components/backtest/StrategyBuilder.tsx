"use client"

// StrategyBuilder — multi-step form that produces a StrategyDef.
// The four steps (Universe / Rules / Rebalance / Period) are rendered
// inline as collapsible sections so power users can edit any field
// without click-stepping through. The "Run backtest" CTA lives at the
// bottom and submits the assembled strategy_def to /api/v1/strategies/run.

import { useCallback, useMemo } from "react"
import { cn } from "@/lib/utils"
import {
  METRIC_CATALOG,
  type EntryRule,
  type RuleOperator,
  type StrategyDef,
} from "@/lib/strategyTypes"

interface Props {
  value: StrategyDef
  onChange: (next: StrategyDef) => void
  onRun: () => void
  isRunning: boolean
}

function rid() {
  return `r-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
}

const SECTION_CARD =
  "rounded-2xl border border-border bg-white p-4 sm:p-5 space-y-3"
const LABEL = "block text-xs font-medium text-caption mb-1"
const INPUT =
  "w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-blue-500"

export default function StrategyBuilder({ value, onChange, onRun, isRunning }: Props) {
  const setField = useCallback(
    (mut: (s: StrategyDef) => void) => {
      const copy: StrategyDef = JSON.parse(JSON.stringify(value))
      mut(copy)
      onChange(copy)
    },
    [value, onChange],
  )

  const rules: EntryRule[] = useMemo(
    () =>
      (value.entry_rules.rules || []).map((r, i) => ({
        id: `r-${i}`,
        ...r,
      })) as EntryRule[],
    [value.entry_rules.rules],
  )

  const updateRule = (idx: number, next: Omit<EntryRule, "id">) => {
    setField((s) => {
      s.entry_rules.rules[idx] = next
    })
  }

  const removeRule = (idx: number) => {
    setField((s) => {
      s.entry_rules.rules = s.entry_rules.rules.filter((_, i) => i !== idx)
    })
  }

  const addRule = () => {
    setField((s) => {
      s.entry_rules.rules = [
        ...s.entry_rules.rules,
        { metric: "yieldiq_score", op: ">=", value: 60 },
      ]
    })
  }

  return (
    <div className="space-y-4">
      {/* ── Step 1: Universe ───────────────────────────────────── */}
      <section className={SECTION_CARD}>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink">1. Universe</h2>
          <span className="text-[11px] text-caption">What stocks can be picked</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
          {(["all", "nifty50", "nifty500", "watchlist", "sector"] as const).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setField((s) => { s.universe.kind = k })}
              className={cn(
                "rounded-lg border px-3 py-2 text-xs font-medium",
                value.universe.kind === k
                  ? "border-blue-500 bg-blue-50 text-blue-700"
                  : "border-border bg-white text-ink hover:bg-gray-50",
              )}
            >
              {k === "all" ? "All NSE" : k === "nifty50" ? "Nifty 50" : k === "nifty500" ? "Nifty 500" : k === "watchlist" ? "Watchlist" : "Sector"}
            </button>
          ))}
        </div>
        {value.universe.kind === "sector" && (
          <div>
            <label className={LABEL}>Sector</label>
            <input
              type="text"
              className={INPUT}
              placeholder="e.g. Information Technology"
              value={value.universe.sector || ""}
              onChange={(e) => setField((s) => { s.universe.sector = e.target.value })}
            />
          </div>
        )}
        {value.universe.kind === "watchlist" && (
          <div>
            <label className={LABEL}>Tickers (comma-separated)</label>
            <input
              type="text"
              className={INPUT}
              placeholder="RELIANCE.NS, TCS.NS, INFY.NS"
              value={(value.universe.tickers || []).join(", ")}
              onChange={(e) =>
                setField((s) => {
                  s.universe.tickers = e.target.value
                    .split(",")
                    .map((t) => t.trim())
                    .filter(Boolean)
                })
              }
            />
          </div>
        )}
      </section>

      {/* ── Step 2: Entry rules ─────────────────────────────────── */}
      <section className={SECTION_CARD}>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink">2. Entry rules</h2>
          <div className="flex items-center gap-2">
            <select
              value={value.entry_rules.logic}
              onChange={(e) =>
                setField((s) => { s.entry_rules.logic = e.target.value as "AND" | "OR" })
              }
              className="rounded-lg border border-border px-2 py-1 text-xs"
            >
              <option value="AND">Match ALL</option>
              <option value="OR">Match ANY</option>
            </select>
            <button
              type="button"
              onClick={addRule}
              className="text-xs font-medium text-blue-600 hover:text-blue-700"
            >
              + Add rule
            </button>
          </div>
        </div>
        {rules.length === 0 ? (
          <p className="text-xs text-caption">No rules yet. Add one to filter the universe.</p>
        ) : (
          <div className="space-y-2">
            {rules.map((r, i) => (
              <RuleRow
                key={r.id}
                rule={r}
                onChange={(next) => updateRule(i, next)}
                onRemove={() => removeRule(i)}
              />
            ))}
          </div>
        )}
      </section>

      {/* ── Step 3: Rebalancing ─────────────────────────────────── */}
      <section className={SECTION_CARD}>
        <h2 className="text-sm font-semibold text-ink">3. Rebalancing</h2>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
          <div>
            <label className={LABEL}>Frequency</label>
            <select
              className={INPUT}
              value={value.rebalance.freq}
              onChange={(e) => setField((s) => { s.rebalance.freq = e.target.value as "monthly" | "quarterly" | "yearly" })}
            >
              <option value="monthly">Monthly</option>
              <option value="quarterly">Quarterly</option>
              <option value="yearly">Yearly</option>
            </select>
          </div>
          <div>
            <label className={LABEL}>Position sizing</label>
            <select
              className={INPUT}
              value={value.rebalance.sizing}
              onChange={(e) => setField((s) => { s.rebalance.sizing = e.target.value as "equal" | "score" | "top_n" })}
            >
              <option value="equal">Equal-weight</option>
              <option value="score">Score-weighted</option>
              <option value="top_n">Top-N (equal)</option>
            </select>
          </div>
          <div>
            <label className={LABEL}>Top N</label>
            <input
              type="number"
              min={1}
              max={100}
              className={INPUT}
              value={value.rebalance.top_n ?? 20}
              onChange={(e) =>
                setField((s) => { s.rebalance.top_n = Math.max(1, Number(e.target.value) || 1) })
              }
            />
          </div>
          <div>
            <label className={LABEL}>Max position size (%)</label>
            <input
              type="number"
              min={1}
              max={100}
              className={INPUT}
              value={value.rebalance.max_position_pct ?? 25}
              onChange={(e) =>
                setField((s) => { s.rebalance.max_position_pct = Math.max(1, Math.min(100, Number(e.target.value) || 25)) })
              }
            />
          </div>
        </div>
      </section>

      {/* ── Step 4: Test period ────────────────────────────────── */}
      <section className={SECTION_CARD}>
        <h2 className="text-sm font-semibold text-ink">4. Test period</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <label className={LABEL}>Start date</label>
            <input
              type="date"
              className={INPUT}
              value={value.test_period.start}
              onChange={(e) => setField((s) => { s.test_period.start = e.target.value })}
            />
          </div>
          <div>
            <label className={LABEL}>End date</label>
            <input
              type="date"
              className={INPUT}
              value={value.test_period.end}
              onChange={(e) => setField((s) => { s.test_period.end = e.target.value })}
            />
          </div>
          <div>
            <label className={LABEL}>Benchmark</label>
            <select
              className={INPUT}
              value={value.test_period.benchmark}
              onChange={(e) =>
                setField((s) => { s.test_period.benchmark = e.target.value as "nifty50" | "nifty500" | "sensex" | "custom" })
              }
            >
              <option value="nifty50">Nifty 50</option>
              <option value="nifty500">Nifty 500</option>
              <option value="sensex">Sensex</option>
              <option value="custom">Custom</option>
            </select>
          </div>
        </div>
        <p className="text-[11px] text-caption">
          Backtest uses CURRENT constituents matching your rules — survivorship bias is present.
          Results are illustrative, not predictive.
        </p>
      </section>

      {/* ── Run CTA ────────────────────────────────────────────── */}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={onRun}
          disabled={isRunning}
          className={cn(
            "rounded-xl px-5 py-2.5 text-sm font-semibold text-white shadow-sm",
            isRunning
              ? "bg-gray-400 cursor-not-allowed"
              : "bg-blue-600 hover:bg-blue-700",
          )}
        >
          {isRunning ? "Running backtest…" : "Run backtest"}
        </button>
      </div>
    </div>
  )
}

// ── Rule row ───────────────────────────────────────────────────────
function RuleRow({
  rule,
  onChange,
  onRemove,
}: {
  rule: EntryRule
  onChange: (r: Omit<EntryRule, "id">) => void
  onRemove: () => void
}) {
  const meta = METRIC_CATALOG.find((m) => m.key === rule.metric) ?? METRIC_CATALOG[0]
  const ops: RuleOperator[] =
    meta.type === "number"
      ? [">=", "<=", ">", "<"]
      : meta.type === "enum"
        ? ["in", "not_in"]
        : ["==", "!="]

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-gray-50 p-2">
      <select
        className="rounded border border-border px-2 py-1 text-xs"
        value={rule.metric}
        onChange={(e) => {
          const newMeta = METRIC_CATALOG.find((m) => m.key === e.target.value)!
          onChange({
            metric: newMeta.key,
            op: newMeta.type === "number" ? ">=" : newMeta.type === "enum" ? "in" : "==",
            value: newMeta.type === "enum" ? [newMeta.options![0]] : newMeta.type === "number" ? 0 : "",
          })
        }}
      >
        {METRIC_CATALOG.map((m) => (
          <option key={m.key} value={m.key}>
            {m.label}
          </option>
        ))}
      </select>
      <select
        className="rounded border border-border px-2 py-1 text-xs"
        value={rule.op}
        onChange={(e) => onChange({ ...rule, op: e.target.value as RuleOperator })}
      >
        {ops.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
      {meta.type === "enum" ? (
        <select
          multiple
          className="rounded border border-border px-2 py-1 text-xs min-w-[160px]"
          value={Array.isArray(rule.value) ? rule.value : [String(rule.value)]}
          onChange={(e) => {
            const selected = Array.from(e.target.selectedOptions).map((o) => o.value)
            onChange({ ...rule, value: selected })
          }}
        >
          {meta.options!.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      ) : meta.type === "number" ? (
        <input
          type="number"
          step="0.01"
          className="rounded border border-border px-2 py-1 text-xs w-28"
          value={typeof rule.value === "number" ? rule.value : Number(rule.value) || 0}
          onChange={(e) => onChange({ ...rule, value: Number(e.target.value) })}
        />
      ) : (
        <input
          type="text"
          className="rounded border border-border px-2 py-1 text-xs"
          value={Array.isArray(rule.value) ? rule.value.join(", ") : String(rule.value)}
          onChange={(e) => onChange({ ...rule, value: e.target.value })}
        />
      )}
      {meta.unit && <span className="text-[11px] text-caption">{meta.unit}</span>}
      <button
        type="button"
        onClick={onRemove}
        className="ml-auto text-[11px] text-red-600 hover:text-red-700"
      >
        Remove
      </button>
    </div>
  )
}
