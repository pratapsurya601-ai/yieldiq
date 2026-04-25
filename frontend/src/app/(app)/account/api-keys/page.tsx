"use client"

// Account → API keys page (Pro tier only).
//
// Lifecycle:
//   1. List the user's active keys (label, prefix, last_used).
//   2. "Create new key" opens an inline modal with a label input.
//   3. On create, the backend returns the RAW key ONCE — we display
//      it in a code block with a copy button and a clear "this is the
//      only time you'll see this" warning. The store never persists it.
//   4. "Revoke" prompts for confirmation, then DELETEs the key.
//
// Tier policy:
//   * Free / Analyst users land on the upsell card → /pricing.
//   * Pro users get the full CRUD UI.

import { useEffect, useState } from "react"
import Link from "next/link"
import api from "@/lib/api"
import { useAuthStore } from "@/store/authStore"

interface ApiKeySummary {
  id: number
  key_prefix: string
  label: string
  created_at: string | null
  last_used_at: string | null
}

interface CreateKeyResponse {
  id: number
  raw: string
  prefix: string
  label: string
  created_at: string | null
  daily_cap: number
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—"
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return "—"
    return d.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    })
  } catch {
    return "—"
  }
}

function fmtRelative(iso: string | null): string {
  if (!iso) return "Never used"
  try {
    const d = new Date(iso)
    const diff = Date.now() - d.getTime()
    if (diff < 0 || isNaN(diff)) return "Never used"
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return "Just now"
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    const days = Math.floor(hrs / 24)
    return `${days}d ago`
  } catch {
    return "Never used"
  }
}

export default function ApiKeysPage() {
  const tier = useAuthStore((s) => s.tier)
  const [keys, setKeys] = useState<ApiKeySummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [newLabel, setNewLabel] = useState("")
  const [creating, setCreating] = useState(false)
  const [justCreated, setJustCreated] = useState<CreateKeyResponse | null>(null)
  const [copied, setCopied] = useState(false)
  const [confirmRevoke, setConfirmRevoke] = useState<number | null>(null)
  const [revoking, setRevoking] = useState(false)

  const isPro = tier === "pro"

  useEffect(() => {
    if (!isPro) {
      setLoading(false)
      return
    }
    let alive = true
    api
      .get("/api/v1/account/api-keys/")
      .then((r) => {
        if (!alive) return
        setKeys(r.data?.keys || [])
        setLoading(false)
      })
      .catch((err) => {
        if (!alive) return
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setError(typeof detail === "string" ? detail : "Failed to load keys.")
        setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [isPro])

  const handleCreate = async () => {
    setCreating(true)
    setError(null)
    try {
      const { data } = await api.post<CreateKeyResponse>(
        "/api/v1/account/api-keys/",
        { label: newLabel.trim() || "Untitled" },
      )
      setJustCreated(data)
      setKeys((prev) => [
        {
          id: data.id,
          key_prefix: data.prefix,
          label: data.label,
          created_at: data.created_at,
          last_used_at: null,
        },
        ...prev,
      ])
      setShowCreate(false)
      setNewLabel("")
    } catch (err: unknown) {
      const ax = err as {
        response?: { status?: number; data?: { detail?: { message?: string } | string } }
      }
      const detail = ax?.response?.data?.detail
      const msg =
        typeof detail === "string"
          ? detail
          : detail?.message || "Could not create key. Please try again."
      setError(msg)
    } finally {
      setCreating(false)
    }
  }

  const handleCopy = () => {
    if (!justCreated) return
    navigator.clipboard.writeText(justCreated.raw)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleRevoke = async (id: number) => {
    setRevoking(true)
    try {
      await api.delete(`/api/v1/account/api-keys/${id}`)
      setKeys((prev) => prev.filter((k) => k.id !== id))
      setConfirmRevoke(null)
    } catch {
      setError("Could not revoke key. Please try again.")
    } finally {
      setRevoking(false)
    }
  }

  // ── Upsell for non-Pro ────────────────────────────────────────────
  if (!isPro) {
    return (
      <div className="max-w-md md:max-w-2xl mx-auto px-4 py-8 space-y-6 pb-20">
        <div className="flex items-center gap-3">
          <Link href="/account" className="text-sm text-caption hover:text-ink">
            {"← Account"}
          </Link>
        </div>
        <h1 className="text-xl font-bold text-ink">API keys</h1>

        <div className="bg-bg dark:bg-surface rounded-2xl border border-border p-6 text-center space-y-4">
          <div className="text-4xl" aria-hidden>
            {"\u{1F511}"}
          </div>
          <h2 className="text-lg font-semibold text-ink">
            API access is a Pro-tier feature
          </h2>
          <p className="text-sm text-body">
            Generate API keys to pull YieldIQ analyses programmatically into
            your sheets, scripts, or research tools. 100 requests per day per
            key, up to 5 keys.
          </p>
          <Link
            href="/pricing"
            className="inline-block py-3 px-5 bg-blue-600 text-white text-sm font-semibold rounded-xl hover:bg-blue-700 transition"
          >
            See pricing
          </Link>
        </div>
      </div>
    )
  }

  // ── Pro user — full UI ────────────────────────────────────────────
  return (
    <div className="max-w-md md:max-w-2xl mx-auto px-4 py-8 space-y-6 pb-20">
      <div className="flex items-center gap-3">
        <Link href="/account" className="text-sm text-caption hover:text-ink">
          {"← Account"}
        </Link>
      </div>

      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-ink">API keys</h1>
        <Link
          href="/api-docs"
          className="text-xs text-blue-600 dark:text-blue-300 hover:underline"
        >
          API docs {"→"}
        </Link>
      </div>

      <p className="text-sm text-body">
        Use these keys to access YieldIQ programmatically. Each key is limited
        to <span className="font-semibold text-ink">100 requests/day</span>.
        You can have up to 5 active keys.
      </p>

      {/* Just-created key — show ONCE */}
      {justCreated && (
        <div className="bg-blue-50 dark:bg-blue-950/30 border-2 border-blue-400 dark:border-blue-700 rounded-2xl p-5 space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-lg" aria-hidden>
              {"⚠️"}
            </span>
            <h2 className="text-sm font-semibold text-ink">
              Save this key now
            </h2>
          </div>
          <p className="text-xs text-body">
            This is the only time you{"’"}ll see the full key. We store
            only its hash. If you lose it, you{"’"}ll have to revoke and
            create a new one.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 bg-bg dark:bg-surface border border-border rounded-lg text-xs font-mono text-ink break-all">
              {justCreated.raw}
            </code>
            <button
              onClick={handleCopy}
              className="px-4 py-2 min-h-[40px] bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 active:scale-[0.97] transition flex-shrink-0"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
          <button
            onClick={() => setJustCreated(null)}
            className="text-xs text-caption hover:text-ink underline"
          >
            I{"’"}ve saved it{" — "}dismiss
          </button>
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <div className="bg-bg dark:bg-surface border border-border rounded-2xl p-5 space-y-3">
          <h2 className="text-sm font-semibold text-ink">Create new key</h2>
          <label className="block">
            <span className="text-xs text-caption">Label (for your reference)</span>
            <input
              type="text"
              value={newLabel}
              maxLength={80}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="e.g. My Sheets script"
              className="mt-1 w-full px-3 py-2 bg-bg dark:bg-surface border border-border rounded-lg text-sm text-ink focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>
          <div className="flex gap-2">
            <button
              onClick={handleCreate}
              disabled={creating}
              className="flex-1 py-2.5 bg-blue-600 text-white text-sm font-semibold rounded-xl hover:bg-blue-700 active:scale-[0.98] transition disabled:opacity-50"
            >
              {creating ? "Creating..." : "Create key"}
            </button>
            <button
              onClick={() => {
                setShowCreate(false)
                setNewLabel("")
              }}
              className="px-4 py-2.5 text-sm font-medium text-body border border-border rounded-xl hover:bg-surface transition"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="bg-red-50 dark:bg-red-950/30 border border-red-300 dark:border-red-800 rounded-xl p-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {/* New key button */}
      {!showCreate && keys.length < 5 && (
        <button
          onClick={() => setShowCreate(true)}
          className="w-full py-3 border-2 border-dashed border-border rounded-xl text-sm font-medium text-body hover:border-blue-400 hover:text-blue-600 dark:hover:text-blue-300 transition"
        >
          + Create new key
        </button>
      )}
      {!showCreate && keys.length >= 5 && (
        <p className="text-xs text-caption text-center">
          You{"’"}ve hit the 5-active-key limit. Revoke one to create another.
        </p>
      )}

      {/* List */}
      {loading ? (
        <p className="text-sm text-caption text-center py-8">Loading...</p>
      ) : keys.length === 0 ? (
        <div className="bg-bg dark:bg-surface border border-border rounded-2xl p-6 text-center">
          <p className="text-sm text-body">
            No API keys yet. Create one to access YieldIQ programmatically.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {keys.map((k) => (
            <div
              key={k.id}
              className="bg-bg dark:bg-surface border border-border rounded-xl p-4 flex items-start justify-between gap-3"
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-ink truncate">
                  {k.label}
                </p>
                <p className="text-xs font-mono text-caption mt-0.5">
                  {k.key_prefix}
                  {"…"}
                </p>
                <p className="text-xs text-caption mt-1">
                  Created {fmtDate(k.created_at)}{" · "}
                  {fmtRelative(k.last_used_at)}
                </p>
              </div>
              {confirmRevoke === k.id ? (
                <div className="flex flex-col gap-1 flex-shrink-0">
                  <button
                    onClick={() => handleRevoke(k.id)}
                    disabled={revoking}
                    className="px-3 py-1.5 bg-red-600 text-white text-xs font-semibold rounded-lg hover:bg-red-700 disabled:opacity-50"
                  >
                    {revoking ? "..." : "Confirm"}
                  </button>
                  <button
                    onClick={() => setConfirmRevoke(null)}
                    className="px-3 py-1.5 text-xs text-caption hover:text-ink"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setConfirmRevoke(k.id)}
                  className="px-3 py-1.5 text-xs font-medium text-red-600 dark:text-red-400 border border-red-300 dark:border-red-800 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/40 flex-shrink-0"
                >
                  Revoke
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
