"use client"

import { cn } from "@/lib/utils"
import FilterRow from "@/components/screener/FilterRow"
import {
  newClause,
  type FilterClause,
  type ScreenerField,
} from "@/lib/screenerFilters"

interface FilterBuilderProps {
  clauses: FilterClause[]
  fields: ScreenerField[]
  sort: string
  limit: number
  sortableFields: string[]
  onClausesChange: (next: FilterClause[]) => void
  onSortChange: (next: string) => void
  onLimitChange: (next: number) => void
  onRun: () => void
  onSave: () => void
  isRunning: boolean
  canSave: boolean
}

export default function FilterBuilder({
  clauses,
  fields,
  sort,
  limit,
  sortableFields,
  onClausesChange,
  onSortChange,
  onLimitChange,
  onRun,
  onSave,
  isRunning,
  canSave,
}: FilterBuilderProps) {
  const updateAt = (idx: number, next: FilterClause) => {
    const copy = clauses.slice()
    copy[idx] = next
    onClausesChange(copy)
  }

  const removeAt = (idx: number) => {
    onClausesChange(clauses.filter((_, i) => i !== idx))
  }

  const addClause = () => {
    onClausesChange([...clauses, newClause()])
  }

  return (
    <div className="rounded-2xl border border-border bg-white p-4 sm:p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ink">Filters</h2>
        <button
          type="button"
          onClick={addClause}
          className="text-xs font-medium text-blue-600 hover:text-blue-700"
        >
          + Add filter
        </button>
      </div>

      {clauses.length === 0 ? (
        <p className="text-xs text-caption">No filters yet. Add one to begin.</p>
      ) : (
        <div className="space-y-2">
          {clauses.map((c, i) => (
            <FilterRow
              key={c.id}
              clause={c}
              fields={fields}
              onChange={(next) => updateAt(i, next)}
              onRemove={() => removeAt(i)}
            />
          ))}
        </div>
      )}

      <div className="flex flex-col gap-3 pt-3 border-t border-border sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <label className="flex flex-col gap-1 text-xs text-caption">
            Sort by
            <select
              value={sort}
              onChange={(e) => onSortChange(e.target.value)}
              className={cn(
                "rounded-lg border border-border bg-bg px-3 py-2 text-sm text-ink",
                "focus:outline-none focus:ring-2 focus:ring-blue-500"
              )}
            >
              {sortableFields.length === 0 && <option value="">Default</option>}
              {sortableFields.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-caption">
            Limit
            <input
              type="number"
              min={1}
              max={500}
              value={limit}
              onChange={(e) => {
                const n = Number(e.target.value)
                onLimitChange(Number.isFinite(n) && n > 0 ? n : 50)
              }}
              className={cn(
                "w-24 rounded-lg border border-border bg-bg px-3 py-2 text-sm text-ink",
                "focus:outline-none focus:ring-2 focus:ring-blue-500"
              )}
            />
          </label>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onSave}
            disabled={!canSave}
            className={cn(
              "rounded-lg border border-border bg-bg px-4 py-2 text-sm font-medium text-body",
              "hover:bg-border transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            Save query
          </button>
          <button
            type="button"
            onClick={onRun}
            disabled={isRunning}
            className={cn(
              "rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white",
              "hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            {isRunning ? "Running..." : "Run Screener"}
          </button>
        </div>
      </div>
    </div>
  )
}
