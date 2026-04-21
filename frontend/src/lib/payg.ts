// payg.ts — purchase flow for the ₹99 / 24 h pay-as-you-go unlock.
//
// Shared by the analysis tier-gate (primary entry point) and any other
// surface that may want to trigger the same flow. Mirrors the pattern of
// `handleUpgrade()` in app/(app)/account/page.tsx but targets the PAYG
// endpoints and persists the resulting unlock into usePaygStore.
//
// Razorpay SDK is loaded on-demand (once per session) so the checkout
// script doesn't add ~40 kB to every page.

import {
  createPaygOrder,
  verifyPaygPayment,
  type PaygCreateOrderResponse,
} from "@/lib/api"
import {
  trackCheckoutOpened,
  trackCheckoutFailed,
  trackPaygUnlocked,
  trackUpgradeClicked,
} from "@/lib/analytics"
import { usePaygStore } from "@/store/paygStore"

declare global {
  interface Window {
    Razorpay: new (options: Record<string, unknown>) => { open: () => void }
  }
}

const RAZORPAY_SRC = "https://checkout.razorpay.com/v1/checkout.js"

async function ensureRazorpayLoaded(): Promise<void> {
  if (typeof window === "undefined") throw new Error("ssr")
  if (window.Razorpay) return
  await new Promise<void>((resolve, reject) => {
    const script = document.createElement("script")
    script.src = RAZORPAY_SRC
    script.onload = () => resolve()
    script.onerror = () => reject(new Error("script_load_failed"))
    document.body.appendChild(script)
  })
}

export interface PaygResult {
  ok: boolean
  /** Short reason tag when ok=false. "cancelled" for user-dismiss (no
   *  toast expected), everything else is worth surfacing. */
  reason?:
    | "cancelled"
    | "script_load"
    | "order_unavailable"   // 503 — PAYG not enabled yet
    | "order_failed"
    | "verify_failed"
    | "unknown"
  /** Human-friendly message for the caller to toast. Absent when
   *  reason === "cancelled". */
  message?: string
  /** Raw order response — populated once we've successfully called
   *  /create-order, useful for debugging. */
  order?: PaygCreateOrderResponse
}

interface StartPaygArgs {
  ticker: string
  /** Prefill the checkout modal — improves conversion. */
  email?: string | null
  /** Analytics source tag — e.g. "analysis_gate", "account". */
  source?: string
}

/**
 * Kick off the PAYG purchase flow end-to-end. Resolves once Razorpay has
 * either succeeded (unlock persisted to usePaygStore + backend) or failed /
 * been dismissed. Does not throw — callers should branch on `result.ok`.
 */
export async function startPaygCheckout({
  ticker,
  email,
  source = "unknown",
}: StartPaygArgs): Promise<PaygResult> {
  // Re-use the existing upgrade_clicked funnel event with a distinct
  // plan id so PAYG clicks show up alongside subscription clicks in GA.
  trackUpgradeClicked("single_analysis", source)

  // 1. Create the Razorpay order on the backend.
  let order: PaygCreateOrderResponse
  try {
    order = await createPaygOrder(ticker)
  } catch (err) {
    const axErr = err as { response?: { status?: number; data?: { detail?: string } } }
    const status = axErr?.response?.status
    trackCheckoutFailed("single_analysis", "init")
    if (status === 503) {
      return {
        ok: false,
        reason: "order_unavailable",
        message: "PAYG not available yet — try again later.",
      }
    }
    return {
      ok: false,
      reason: "order_failed",
      message:
        axErr?.response?.data?.detail ??
        "Could not start payment. Please try again.",
    }
  }

  // 2. Load Razorpay SDK if not already present.
  try {
    await ensureRazorpayLoaded()
  } catch {
    trackCheckoutFailed("single_analysis", "script_load")
    return {
      ok: false,
      reason: "script_load",
      message: "Payment form failed to load. Check your connection and retry.",
      order,
    }
  }

  // 3. Open the modal and wait for the handler / dismiss.
  trackCheckoutOpened("single_analysis", "onetime")

  return new Promise<PaygResult>((resolve) => {
    const options = {
      key: order.key_id,
      order_id: order.order_id,
      amount: order.amount,
      currency: order.currency,
      name: order.name,
      description: order.description,
      prefill: { email: email || "" },
      theme: { color: "#1D4ED8" },
      modal: {
        ondismiss: () => {
          trackCheckoutFailed("single_analysis", "cancelled")
          resolve({ ok: false, reason: "cancelled", order })
        },
      },
      handler: async (response: {
        razorpay_order_id: string
        razorpay_payment_id: string
        razorpay_signature: string
      }) => {
        try {
          const verify = await verifyPaygPayment({
            razorpay_order_id: response.razorpay_order_id,
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_signature: response.razorpay_signature,
            ticker,
          })
          if (verify.ok) {
            // Persist locally so gate + badges update immediately.
            usePaygStore.getState().addUnlock(verify.unlock.ticker)
            trackPaygUnlocked(verify.unlock.ticker)
            resolve({
              ok: true,
              message: `Unlocked for ${verify.unlock.hours ?? 24}h`,
              order,
            })
          } else {
            trackCheckoutFailed("single_analysis", "verify")
            resolve({
              ok: false,
              reason: "verify_failed",
              message:
                "Payment received but unlock failed — email support@yieldiq.in with your payment ID.",
              order,
            })
          }
        } catch {
          trackCheckoutFailed("single_analysis", "verify")
          resolve({
            ok: false,
            reason: "verify_failed",
            message:
              "Payment received but unlock failed — email support@yieldiq.in with your payment ID.",
            order,
          })
        }
      },
    }

    try {
      const rzp = new window.Razorpay(options)
      rzp.open()
    } catch {
      trackCheckoutFailed("single_analysis", "init")
      resolve({
        ok: false,
        reason: "unknown",
        message: "Could not open payment form. Please try again.",
        order,
      })
    }
  })
}
