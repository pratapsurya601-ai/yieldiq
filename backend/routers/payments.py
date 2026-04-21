# backend/routers/payments.py
# Razorpay payment integration for YieldIQ subscriptions.
from __future__ import annotations
import os
import sys
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from backend.middleware.auth import get_current_user, invalidate_tier_cache

RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
if not RAZORPAY_KEY_ID:
    import logging as _rl
    _rl.getLogger("yieldiq.payments").warning("RAZORPAY_KEY_ID not set — payments disabled")

# Razorpay Subscription plan IDs (created in Razorpay Dashboard →
# Subscriptions → Plans). Set these on Railway after creating each
# plan. The env var name pattern matches the (tier, billing) tuple
# used by the frontend so `create-subscription?plan_id=analyst&
# billing=monthly` resolves to RAZORPAY_PLAN_ANALYST_MONTHLY.
#
# If any of these are missing, create-subscription returns 503 for
# that specific (tier, billing) pair — other tiers still work.
RAZORPAY_PLAN_IDS: dict[str, str] = {
    "analyst_monthly": os.environ.get("RAZORPAY_PLAN_ANALYST_MONTHLY", "").strip(),
    "analyst_annual":  os.environ.get("RAZORPAY_PLAN_ANALYST_ANNUAL", "").strip(),
    "pro_monthly":     os.environ.get("RAZORPAY_PLAN_PRO_MONTHLY", "").strip(),
    "pro_annual":      os.environ.get("RAZORPAY_PLAN_PRO_ANNUAL", "").strip(),
}
_missing_plan_ids = [k for k, v in RAZORPAY_PLAN_IDS.items() if not v]
if _missing_plan_ids:
    import logging as _rl2
    _rl2.getLogger("yieldiq.payments").warning(
        "Missing Razorpay plan IDs for: %s — subscription upgrades "
        "to those tiers will 503 until env vars are set on Railway.",
        ", ".join(_missing_plan_ids),
    )


    # Debug endpoint removed — live payments active

PLANS = {
    # Recurring subscriptions — the two paid tiers.
    "analyst": {
        "name": "Analyst",
        "amount": 79900,  # ₹799 in paise
        "currency": "INR",
        "interval": "monthly",
        "description": (
            "Unlimited analyses, Portfolio Prism, multi-account portfolios, "
            "AI summaries, Concall AI, Time Machine. For serious DIY investors."
        ),
    },
    "analyst_annual": {
        "name": "Analyst (Annual)",
        "amount": 699900,  # ₹6,999 in paise — 27% off monthly × 12
        "currency": "INR",
        "interval": "annual",
        "description": (
            "All Analyst features, billed yearly. Save ₹2,589/yr (~27%) vs monthly."
        ),
    },
    "pro": {
        "name": "Pro",
        "amount": 149900,  # ₹1,499 in paise
        "currency": "INR",
        "interval": "monthly",
        "description": (
            "Everything in Analyst + CSV/PDF export, API access (100/day), "
            "priority compute, 10 broker accounts, save + share custom screens."
        ),
    },
    "pro_annual": {
        "name": "Pro (Annual)",
        "amount": 1399900,  # ₹13,999 in paise — 22% off monthly × 12
        "currency": "INR",
        "interval": "annual",
        "description": (
            "All Pro features, billed yearly. Save ₹3,989/yr (~22%) vs monthly."
        ),
    },
    # One-time pay-as-you-go — casual visitor who wants ONE analysis.
    # 24h unlock for a single ticker. Natural upsell: at 8 analyses
    # (₹99 × 8 = ₹792) they're already past the Analyst monthly price.
    "single_analysis": {
        "name": "Single Analysis",
        "amount": 9900,  # ₹99 in paise
        "currency": "INR",
        "interval": "one_time",
        "description": (
            "24-hour access to a full Prism analysis for ONE stock. "
            "Covers Fair Value, scenarios, Moat, AI summary, Compare, "
            "and shareable Report Card."
        ),
    },
}

# Free-tier monthly analysis quota. Enforced by the analysis router
# via the middleware that consults users_meta.tier + the monthly usage
# counter. Documented here so a single edit updates both docs and code.
FREE_TIER_MONTHLY_ANALYSIS_LIMIT = 5


@router.get("/plans")
async def get_plans():
    """Get available subscription plans + one-time purchase options."""
    return {
        "plans": [
            {"id": "analyst", **PLANS["analyst"], "display_price": "₹799/mo"},
            {"id": "analyst_annual", **PLANS["analyst_annual"], "display_price": "₹6,999/yr"},
            {"id": "pro", **PLANS["pro"], "display_price": "₹1,499/mo"},
            {"id": "pro_annual", **PLANS["pro_annual"], "display_price": "₹13,999/yr"},
            {"id": "single_analysis", **PLANS["single_analysis"], "display_price": "₹99 / analysis"},
        ],
        "free_tier_limit": FREE_TIER_MONTHLY_ANALYSIS_LIMIT,
        "key_id": RAZORPAY_KEY_ID,
    }


@router.post("/create-order")
async def create_order(
    plan_id: str = "pro",
    user: dict = Depends(get_current_user),
):
    """Create a Razorpay order for the selected plan."""
    if plan_id not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    plan = PLANS[plan_id]

    try:
        import razorpay
        client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        order = client.order.create({
            "amount": plan["amount"],
            "currency": plan["currency"],
            "receipt": f"yiq_{user['user_id']}_{plan_id}",
            "notes": {
                "user_id": user["user_id"],
                "email": user["email"],
                "plan": plan_id,
            },
        })
        return {
            "order_id": order["id"],
            "amount": plan["amount"],
            "currency": plan["currency"],
            "key_id": RAZORPAY_KEY_ID,
            "plan": plan_id,
            "name": "YieldIQ",
            "description": plan["description"],
        }
    except Exception as e:
        import logging
        logging.getLogger("yieldiq.payments").error(f"create-order failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Payment init failed: {type(e).__name__}: {e}")


@router.post("/create-subscription")
async def create_subscription(
    plan_id: str,
    billing: str = "monthly",
    user: dict = Depends(get_current_user),
):
    """Create a Razorpay Subscription for analyst/pro at monthly/annual.

    Use this for recurring plans. For the one-time ₹99 PAYG single
    analysis use /create-order instead.

    Returns subscription_id + short_url; frontend opens the Razorpay
    checkout modal with subscription_id. On first charge, Razorpay
    fires a webhook (subscription.activated) that promotes the user
    tier — no verify step needed for the initial payment.
    """
    if plan_id not in ("analyst", "pro"):
        raise HTTPException(
            status_code=400,
            detail="plan_id must be 'analyst' or 'pro' (use /create-order for ₹99 single-analysis)",
        )
    if billing not in ("monthly", "annual"):
        raise HTTPException(
            status_code=400, detail="billing must be 'monthly' or 'annual'",
        )

    rz_plan_key = f"{plan_id}_{billing}"
    rz_plan_id = RAZORPAY_PLAN_IDS.get(rz_plan_key, "")
    if not rz_plan_id:
        # Tell ops exactly which env var is missing. Surface as 503
        # (service unavailable) rather than 500 — it's a config hole,
        # not an app bug.
        raise HTTPException(
            status_code=503,
            detail=(
                f"This tier isn't available for purchase yet. "
                f"Razorpay plan ID for {rz_plan_key} not configured. "
                f"Set env var RAZORPAY_PLAN_{rz_plan_key.upper()} on Railway."
            ),
        )

    try:
        import razorpay
        client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

        # total_count: how many billing cycles before Razorpay auto-
        # cancels. 12 monthlies = 1 year; 1 annual = 1 year. After that
        # Razorpay emails the user to renew — gives us a natural
        # "cancel anytime without code" safety rail.
        total_count = 12 if billing == "monthly" else 1

        sub = client.subscription.create({
            "plan_id": rz_plan_id,
            "total_count": total_count,
            "customer_notify": 1,
            "notes": {
                "user_id": user["user_id"],
                "email": user["email"],
                "tier": plan_id,
                "billing": billing,
            },
        })

        plan_key_display = f"{plan_id}_{'annual' if billing == 'annual' else ''}".rstrip("_") or plan_id
        display_plan = PLANS.get(plan_key_display) or PLANS.get(plan_id, {})

        return {
            "subscription_id": sub["id"],
            "short_url": sub.get("short_url"),
            "key_id": RAZORPAY_KEY_ID,
            "plan": plan_id,
            "billing": billing,
            "amount": display_plan.get("amount"),
            "currency": display_plan.get("currency", "INR"),
            "name": "YieldIQ",
            "description": display_plan.get("description", ""),
        }
    except Exception as e:
        import logging
        logging.getLogger("yieldiq.payments").error(
            f"create-subscription failed for {user.get('email')} "
            f"plan={plan_id} billing={billing} rz_plan_id={rz_plan_id}: "
            f"{type(e).__name__}: {e}"
        )
        # Surface the actual Razorpay error message (e.g. "plan id is
        # invalid", "authentication failed") so ops can fix it without
        # needing log access. Safe to expose — no secrets in these.
        err_msg = str(e).strip() or type(e).__name__
        raise HTTPException(
            status_code=500,
            detail=f"Subscription init failed: {type(e).__name__}: {err_msg}",
        )


@router.post("/verify-subscription")
async def verify_subscription(
    razorpay_subscription_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
    plan_id: str,
    user: dict = Depends(get_current_user),
):
    """Verify the first-charge signature for a subscription and
    promote the user's tier in users_meta.

    Note: the source of truth for ongoing subscription status is the
    webhook (subscription.activated / subscription.charged / .halted /
    .cancelled). This endpoint handles the synchronous post-checkout
    confirmation so the UI can flip the user's tier immediately
    without waiting for the webhook.
    """
    import hmac
    import hashlib
    import logging
    logger = logging.getLogger("yieldiq.payments")

    try:
        # Razorpay's Python SDK `verify_payment_signature` is Order-
        # based and demands `razorpay_order_id` — passing subscription
        # kwargs yields KeyError. For Subscriptions the canonical
        # signature is HMAC_SHA256(secret, f"{payment_id}|{sub_id}").
        # See https://razorpay.com/docs/payments/subscriptions/verify-signature/
        expected_signature = hmac.new(
            RAZORPAY_KEY_SECRET.encode("utf-8"),
            f"{razorpay_payment_id}|{razorpay_subscription_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, razorpay_signature):
            logger.warning(
                "verify-subscription signature mismatch for sub=%s payment=%s",
                razorpay_subscription_id, razorpay_payment_id,
            )
            raise HTTPException(
                status_code=400,
                detail="Subscription verification failed (signature mismatch)",
            )

        new_tier = plan_id if plan_id in ("analyst", "pro") else "analyst"

        # Promote tier in users_meta. Schema: PK is `id` (UUID), not
        # `user_id`. Only touch `tier` — we track subscription metadata
        # separately in the `subscriptions` table where the schema
        # supports it.
        try:
            from db.supabase_client import get_client
            client_sb = get_client()
            if client_sb:
                client_sb.table("users_meta").update({
                    "tier": new_tier,
                }).eq("id", user["user_id"]).execute()

                # Upsert subscription metadata so the webhook can map
                # razorpay_sub_id → user_email for lifecycle events.
                # on_conflict=razorpay_sub_id (UNIQUE) makes this safe
                # for repeat calls if user retries checkout.
                client_sb.table("subscriptions").upsert({
                    "user_email": user["email"],
                    "razorpay_sub_id": razorpay_subscription_id,
                    "razorpay_payment_id": razorpay_payment_id,
                    "razorpay_plan_id": RAZORPAY_PLAN_IDS.get(
                        f"{new_tier}_monthly", ""
                    ),
                    "tier": new_tier,
                    "status": "active",
                }, on_conflict="razorpay_sub_id").execute()
        except Exception as sb_exc:
            # Don't fail the whole request if Supabase write fails —
            # the user has already paid. Log loudly so we can
            # reconcile by hand.
            logger.error(
                "verify-subscription Supabase write failed for %s sub=%s: %s: %s",
                user.get("email"), razorpay_subscription_id,
                type(sb_exc).__name__, sb_exc,
            )

        # Invalidate the per-user tier cache so the very next API
        # request reads the fresh tier from Supabase. Without this,
        # there's a ~60s window where the user is paid but still
        # rate-limited at free tier.
        invalidate_tier_cache(user["user_id"])

        # Best-effort SQLite auth sync (legacy self-hosted path — no-op
        # in production where Supabase is the auth backend).
        try:
            _dashboard = os.path.join(_ROOT, "dashboard")
            if _dashboard not in sys.path:
                sys.path.insert(0, _dashboard)
            from auth import set_tier
            set_tier(user["email"], new_tier)
        except Exception:
            pass

        return {
            "ok": True,
            "tier": new_tier,
            "subscription_id": razorpay_subscription_id,
            "message": f"Subscribed to {new_tier.title()} plan",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "verify-subscription failed: %s: %s",
            type(e).__name__, e,
        )
        raise HTTPException(
            status_code=500,
            detail=f"verify-subscription failed: {type(e).__name__}: {e}",
        )


@router.post("/verify")
async def verify_payment(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
    plan_id: str = "pro",
    user: dict = Depends(get_current_user),
):
    """Verify Razorpay payment and upgrade user tier.

    Legacy one-time Order verification — kept for the ₹99 PAYG path
    and any old clients still mid-flight. New monthly/annual flows
    should use /verify-subscription.
    """
    try:
        import razorpay
        client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

        # Verify signature
        client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        })

        # Payment verified — upgrade user tier
        new_tier = plan_id if plan_id in ("pro", "analyst") else "pro"

        # Update in Supabase
        try:
            from db.supabase_client import get_client
            client_sb = get_client()
            if client_sb:
                client_sb.table("users_meta").upsert({
                    "user_id": user["user_id"],
                    "tier": new_tier,
                }).execute()
        except Exception:
            pass

        # Update in SQLite auth
        try:
            _dashboard = os.path.join(_ROOT, "dashboard")
            if _dashboard not in sys.path:
                sys.path.insert(0, _dashboard)
            from auth import set_tier
            set_tier(user["email"], new_tier)
        except Exception:
            pass

        return {
            "ok": True,
            "tier": new_tier,
            "message": f"Upgraded to {new_tier.title()} plan",
        }
    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Payment verification failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook")
async def razorpay_webhook(request: Request):
    """Razorpay subscription lifecycle webhook.

    Source of truth for ongoing subscription state. Handles:
      - subscription.activated   — first charge succeeded → promote tier
      - subscription.charged     — renewal succeeded → log (tier unchanged)
      - subscription.halted      — retries failing → log, keep tier (Razorpay
                                    retries for ~3 days before cancelling)
      - subscription.cancelled   — user cancelled / all retries failed → demote
      - subscription.completed   — total_count reached → demote

    Security: verifies `X-Razorpay-Signature` against the raw body +
    `RAZORPAY_WEBHOOK_SECRET`. Unknown events are ack'd with 200 so
    Razorpay doesn't retry them.

    Idempotency: upserts by `razorpay_subscription_id`. Repeat events
    are safe — the tier either re-applies (activated) or re-demotes
    (cancelled) without side-effects.

    Railway setup:
      1. Razorpay dashboard → Settings → Webhooks → + Add
      2. URL: https://api.yieldiq.in/api/v1/payments/webhook
      3. Secret: generate random string (e.g. `openssl rand -hex 32`)
      4. Events: subscription.activated, .charged, .halted, .cancelled, .completed
      5. Copy the secret into Railway env var RAZORPAY_WEBHOOK_SECRET
    """
    import json
    import logging
    import razorpay
    logger = logging.getLogger("yieldiq.payments.webhook")

    if not RAZORPAY_WEBHOOK_SECRET:
        logger.error("RAZORPAY_WEBHOOK_SECRET not set — rejecting webhook")
        raise HTTPException(status_code=503, detail="Webhook not configured")

    body_bytes = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not signature:
        logger.warning("webhook missing X-Razorpay-Signature header")
        raise HTTPException(status_code=400, detail="Missing signature")

    # 1. Verify signature against raw body. CRITICAL — do not accept
    # unsigned webhooks; anyone could forge tier upgrades otherwise.
    try:
        client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        client.utility.verify_webhook_signature(
            body_bytes.decode("utf-8"),
            signature,
            RAZORPAY_WEBHOOK_SECRET,
        )
    except Exception as e:
        logger.warning(
            "webhook signature verification failed: %s: %s",
            type(e).__name__, e,
        )
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 2. Parse body.
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception as e:
        logger.error("webhook body parse failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event", "")
    sub_entity = (
        (payload.get("payload", {}) or {})
        .get("subscription", {}) or {}
    ).get("entity", {}) or {}
    subscription_id = sub_entity.get("id")
    notes = sub_entity.get("notes", {}) or {}
    tier_hint = notes.get("tier")  # set by create_subscription handler

    logger.info(
        "webhook received: event=%s sub_id=%s tier_hint=%s",
        event, subscription_id, tier_hint,
    )

    # 3. No subscription context (e.g. payment.captured standalone) —
    # ack and skip. Not an error.
    if not subscription_id:
        return {"ok": True, "ignored": event}

    # 4. Map event to tier action. Always return 200 on handler
    # exceptions so Razorpay doesn't pile up retries for something we
    # need to debug manually.
    try:
        from db.supabase_client import get_client
        client_sb = get_client()
        if client_sb is None:
            logger.error("webhook: Supabase unavailable, skipping tier update")
            return {"ok": True, "warning": "no-supabase-client"}

        # Look up user by razorpay_sub_id in the `subscriptions` table.
        # users_meta doesn't store subscription_id directly — that'd
        # be a schema dead-end since users can resubscribe over time.
        sub_row = client_sb.table("subscriptions").select(
            "user_email,tier"
        ).eq("razorpay_sub_id", subscription_id).limit(1).execute()
        rows = sub_row.data or []
        if not rows:
            logger.warning(
                "webhook: no subscriptions row for sub=%s event=%s "
                "(verify-subscription may have missed the initial insert)",
                subscription_id, event,
            )
            return {"ok": True, "warning": "no-subscriptions-row"}
        user_email = rows[0]["user_email"]
        stored_tier = rows[0].get("tier") or "analyst"

        if event == "subscription.activated":
            new_tier = tier_hint if tier_hint in ("analyst", "pro") else stored_tier
            client_sb.table("users_meta").update({
                "tier": new_tier,
            }).eq("email", user_email).execute()
            client_sb.table("subscriptions").update({
                "status": "active",
                "tier": new_tier,
            }).eq("razorpay_sub_id", subscription_id).execute()
            logger.info(
                "webhook promoted %s (sub=%s) to tier=%s",
                user_email, subscription_id, new_tier,
            )

        elif event == "subscription.charged":
            # Successful renewal — no tier change, just log & stamp.
            client_sb.table("subscriptions").update({
                "status": "active",
            }).eq("razorpay_sub_id", subscription_id).execute()
            logger.info("webhook renewal charged: sub=%s", subscription_id)

        elif event == "subscription.halted":
            # Razorpay retries failed cards for ~3 days. Do NOT demote
            # yet — the user's card may be temporarily declined. Log
            # for ops visibility; Razorpay will fire .cancelled if all
            # retries fail, which IS the demote signal.
            client_sb.table("subscriptions").update({
                "status": "halted",
            }).eq("razorpay_sub_id", subscription_id).execute()
            logger.warning(
                "webhook subscription halted (keeping tier): %s sub=%s",
                user_email, subscription_id,
            )

        elif event in ("subscription.cancelled", "subscription.completed"):
            # User cancelled OR retry window expired OR total_count
            # reached. Demote to free immediately.
            client_sb.table("users_meta").update({
                "tier": "free",
            }).eq("email", user_email).execute()
            client_sb.table("subscriptions").update({
                "status": event.split(".")[-1],  # "cancelled" or "completed"
            }).eq("razorpay_sub_id", subscription_id).execute()
            logger.info(
                "webhook demoted %s (sub=%s) to free (%s)",
                user_email, subscription_id, event,
            )

        else:
            # subscription.pending, subscription.paused, etc. — ack.
            logger.info("webhook event not handled: %s", event)

    except Exception as e:
        # Don't 500 — Razorpay would retry forever. Log loudly and ack.
        logger.exception(
            "webhook handler failed event=%s sub=%s: %s",
            event, subscription_id, e,
        )
        return {"ok": True, "warning": str(e)}

    return {"ok": True, "event": event}
