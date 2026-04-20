"use client"

import { cn } from "@/lib/utils"
import {
  FILTER_OPERATORS,
  type FilterClause,
  type FilterOperator,
  type ScreenerField,
} from "@/lib/screenerFilters"

// Single editable clause in the filter builder. Pure controlled component —
// owns no state of its own so the parent can round-trip through the URL
// without an effect dance.

interface FilterRowProps {
  clause: FilterClause
  fields: ScreenerField[]
  onChange: (next: FilterClause) => void
  onRemove: () => void
}

// For string fields, equality makes sense but magnitude does not.
const STRING_OPS: FilterOperator[] = ["=", "!="]

export default function FilterRow({ clause, fields, onChange, onRemove }: FilterRowProps) {
  const selectedField = fields.find((f) => f.key === clause.field)
  const isString = selectedField?.type === "string"
  const availableOps = isString ? STRING_OPS : FILTER_OPERATORS.filter((op) => op !== "=" && op !== "!=")

  // When the field type changes, snap the operator to a sensible default
  // instead of letting an invalid combo (e.g. sector < tech) leak through.
  const handleFieldChange = (key: string) => {
    const nextField = fields.find((f) => f.key === key)
    const nextIsString = nextField?.type === "string"
    const defaultOp: FilterOperator = nextIsString ? "=" : ">"
    onChange({
      ...clause,
      field: key,
      op: defaultOp,
      value: "",
    })
  }

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <select
        aria-label="Field"
        value={clause.field}
        onChange={(e) => handleFieldChange(e.target.value)}
        className={cn(
          "flex-1 min-w-0 rounded-lg border border-border bg-bg",
          "px-3 py-2 text-sm text-ink",
          "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        )}
      >
        <option value="">Select field...</option>
        {fields.map((f) => (
          <option key={f.key} value={f.key}>
            {f.label}
            {f.unit ? ` (${f.unit})` : ""}
          </option>
        ))}
      </select>

      <select
        aria-label="Operator"
        value={clause.op}
        onChange={(e) => onChange({ ...clause, op: e.target.value as FilterOperator })}
        disabled={!clause.field}
        className={cn(
          "w-full sm:w-20 rounded-lg border border-border bg-bg",
          "px-3 py-2 text-sm text-ink",
          "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
          "disabled:opacity-50"
        )}
      >
        {availableOps.map((op) => (
          <option key={op} value={op}>
            {op}
          </option>
        ))}
      </select>

      {isString && selectedField?.options ? (
        <select
          aria-label="Value"
          value={clause.value}
          onChange={(e) => onChange({ ...clause, value: e.target.value })}
          className={cn(
            "flex-1 min-w-0 rounded-lg border border-border bg-bg",
            "px-3 py-2 text-sm text-ink",
            "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          )}
        >
          <option value="">Select...</option>
          {selectedField.options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      ) : (
        <input
          aria-label="Value"
          type={isString ? "text" : "number"}
          inputMode={isString ? "text" : "decimal"}
          step="any"
          value={clause.value}
          onChange={(e) => onChange({ ...clause, value: e.target.value })}
          disabled={!clause.field}
          placeholder="Value"
          className={cn(
            "flex-1 min-w-0 rounded-lg border border-border bg-bg",
            "px-3 py-2 text-sm text-ink",
            "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
            "disabled:opacity-50"
          )}
        />
      )}

      <button
        type="button"
        onClick={onRemove}
        aria-label="Remove filter"
        className={cn(
          "shrink-0 rounded-lg border border-border bg-bg",
          "h-9 w-9 flex items-center justify-center",
          "text-caption hover:text-red-600 hover:border-red-200 hover:bg-red-50",
          "transition-colors"
        )}
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}
