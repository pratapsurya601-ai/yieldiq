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
    ticker: str | None = None,
    user: dict = Depends(get_current_user),
):
    """Create a Razorpay order for a one-time purchase.

    For `plan_id="single_analysis"` (₹99 PAYG), `ticker` is required —
    the unlock is scoped to that exact ticker. The ticker is stamped
    into Razorpay order notes so /verify can persist the unlock row
    against the right symbol.
    """
    if plan_id not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")
    if plan_id == "single_analysis" and not ticker:
        raise HTTPException(
            status_code=400,
            detail="ticker is required for single_analysis purchases",
        )

    plan = PLANS[plan_id]

    try:
        import razorpay
        client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        notes = {
            "user_id": user["user_id"],
            "email": user["email"],
            "plan": plan_id,
        }
        if ticker:
            # Strip market suffix so we can match on bare symbol in the
            # unlocks table (ticker may arrive as "TCS" or "TCS.NS").
            notes["ticker"] = ticker.upper().strip()
        # Razorpay caps `receipt` at 40 chars. `user_id` is a 36-char UUID,
        # so the original `yiq_{uuid}_{plan_id}` format blew past that
        # (56+ chars) and every PAYG checkout failed with:
        #   BadRequestError: receipt: the length must be no more than 40.
        # Shortened to the first 8 hex chars of the UUID (still unique per
        # user in practice — collision risk ~1 in 4B within a tier) and
        # defensively truncated to 40 so a future longer `plan_id` can't
        # reintroduce the bug. Traceability to the user is preserved via
        # the `notes` dict (which carries the full user_id + email).
        _uid8 = str(user["user_id"]).replace("-", "")[:8]
        _receipt = f"yiq_{_uid8}_{plan_id}"[:40]
        order = client.order.create({
            "amount": plan["amount"],
            "currency": plan["currency"],
            "receipt": _receipt,
            "notes": notes,
        })
        return {
            "order_id": order["id"],
            "amount": plan["amount"],
            "currency": plan["currency"],
            "key_id": RAZORPAY_KEY_ID,
            "plan": plan_id,
            "ticker": notes.get("ticker"),
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
    ticker: str | None = None,
    user: dict = Depends(get_current_user),
):
    """Verify a one-time Razorpay Order payment.

    Two modes:
      - plan_id="single_analysis"  → ₹99 PAYG. Inserts a row into
        payg_unlocks so the user can access that ticker for 24h even
        if their free-tier monthly quota is exhausted. `ticker` is
        required in this mode.
      - plan_id="pro" | "analyst"  → legacy one-time upgrade path
        (superseded by /create-subscription for new flows; kept for
        in-flight old clients).
    """
    import logging
    logger = logging.getLogger("yieldiq.payments")

    try:
        import razorpay
        client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

        # Verify signature (Order-based — SDK's default works here).
        client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        })

        # Branch 1: PAYG single-analysis — record the unlock, don't
        # touch tier. These users stay on 'free' tier but gain 24h
        # access to one specific ticker.
        if plan_id == "single_analysis":
            if not ticker:
                raise HTTPException(
                    status_code=400,
                    detail="ticker is required for single_analysis",
                )
            _ticker = ticker.upper().strip()
            try:
                from db.supabase_client import get_admin_client
                client_sb = get_admin_client()
                if client_sb is not None:
                    # on_conflict=razorpay_payment_id makes retries
                    # idempotent — a second /verify call with the same
                    # payment_id doesn't duplicate the unlock row.
                    client_sb.table("payg_unlocks").upsert({
                        "user_email": user["email"],
                        "ticker": _ticker,
                        "razorpay_payment_id": razorpay_payment_id,
                        "razorpay_order_id": razorpay_order_id,
                        "amount_paise": PLANS["single_analysis"]["amount"],
                    }, on_conflict="razorpay_payment_id").execute()
                    logger.info(
                        "PAYG unlock recorded: %s ticker=%s payment=%s",
                        user["email"], _ticker, razorpay_payment_id,
                    )
            except Exception as exc:
                # User paid — don't 500. Log loudly; we can backfill.
                logger.error(
                    "PAYG unlock persist failed for %s ticker=%s: %s: %s",
                    user["email"], _ticker,
                    type(exc).__name__, exc,
                )
            return {
                "ok": True,
                "unlock": {"ticker": _ticker, "hours": 24},
                "message": f"Analysis unlocked for {_ticker} (24 hours)",
            }

        # Branch 2: legacy tier upgrade via one-time order.
        new_tier = plan_id if plan_id in ("pro", "analyst") else "pro"
        try:
            from db.supabase_client import get_admin_client
            client_sb = get_admin_client()
            if client_sb is not None:
                client_sb.table("users_meta").update({
                    "tier": new_tier,
                }).eq("id", user["user_id"]).execute()
        except Exception as exc:
            logger.error(
                "verify-order users_meta update failed for %s: %s: %s",
                user["email"], type(exc).__name__, exc,
            )

        invalidate_tier_cache(user["user_id"])

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
    except HTTPException:
        raise
    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Payment verification failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────
# PAYG unlock helpers (for tier-gating logic elsewhere in the app)
# ─────────────────────────────────────────────────────────────────

def has_active_payg_unlock(email: str, ticker: str, hours: int = 24) -> bool:
    """True if this user bought a single_analysis unlock for this
    ticker within the last `hours` (default 24). Falls back to False
    on any Supabase error — callers should degrade gracefully."""
    if not email or not ticker:
        return False
    try:
        from db.supabase_client import get_admin_client
        from datetime import datetime, timedelta, timezone
        client_sb = get_admin_client()
        if client_sb is None:
            return False
        _ticker = ticker.upper().strip()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = (
            client_sb.table("payg_unlocks")
            .select("id")
            .eq("user_email", email)
            .eq("ticker", _ticker)
            .gte("unlocked_at", cutoff)
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception:
        return False


@router.get("/payg-unlocks")
async def list_payg_unlocks(user: dict = Depends(get_current_user)):
    """List the caller's active (within 24h) PAYG unlocks. Frontend
    uses this to badge tickers as 'unlocked' in the UI and avoid
    prompting to pay again."""
    try:
        from db.supabase_client import get_admin_client
        from datetime import datetime, timedelta, timezone
        client_sb = get_admin_client()
        if client_sb is None:
            return {"unlocks": []}
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        result = (
            client_sb.table("payg_unlocks")
            .select("ticker,unlocked_at,razorpay_payment_id")
            .eq("user_email", user["email"])
            .gte("unlocked_at", cutoff)
            .order("unlocked_at", desc=True)
            .execute()
        )
        return {"unlocks": result.data or []}
    except Exception as e:
        import logging
        logging.getLogger("yieldiq.payments").warning(
            "list_payg_unlocks failed for %s: %s", user.get("email"), e,
        )
        return {"unlocks": []}


# ────────────────────────────────────────────────────────────────
# Webhook idempotency helpers
#
# Razorpay does not put a single opaque event-UUID in the body, and
# the `x-razorpay-event-id` header is not consistently present across
# older plan events. We therefore synthesise a deterministic dedup
# key from three body fields that together uniquely identify a
# logical event delivery: (account_id, event, created_at). The same
# webhook replayed by Razorpay carries identical values for all
# three; a legitimately-new event differs on created_at at minimum.
#
# If all three fields are missing we return None — the caller then
# skips the idempotency shortcut and relies on the per-event
# handlers' own upsert-by-subscription-id shape-idempotency. This is
# strictly a noise / side-effect reduction; the shape of the users_meta
# + subscriptions rows is the same either way.
# ────────────────────────────────────────────────────────────────
def _razorpay_event_id(payload: dict) -> str | None:
    """Build a stable dedup key for a Razorpay webhook payload.

    Preference order:
      1. `payload["id"]` — if Razorpay ever populates a single
         event-UUID at the top level, use it directly.
      2. (account_id, event, created_at) composite — the documented
         stable tuple across retries of the same logical event.
    Returns None if we can't construct either form (caller falls
    back to the shape-idempotency of the downstream handlers).
    """
    if not isinstance(payload, dict):
        return None
    # Some Razorpay account configs include a top-level `id` on the
    # event envelope. Prefer it when present.
    top_id = payload.get("id")
    if isinstance(top_id, str) and top_id.strip():
        return f"rzp:{top_id.strip()}"

    account_id = payload.get("account_id") or ""
    event = payload.get("event") or ""
    created_at = payload.get("created_at")
    if not (account_id and event and created_at is not None):
        return None
    return f"rzp:{account_id}:{event}:{created_at}"


def _claim_webhook_event(event_id: str, event_type: str, logger) -> bool:
    """Attempt to claim this event_id in `webhook_events`.

    Returns True if this event has ALREADY been processed (i.e. the
    INSERT raised a unique-constraint violation) — the caller MUST
    then return 200 OK without re-running the handler.

    Returns False on successful insert OR on any infra failure
    (Supabase down, table missing pre-migration, network hiccup) —
    the caller then proceeds with normal processing. We deliberately
    fail-open on insert errors because re-running a shape-idempotent
    handler is strictly safer than dropping a real event.
    """
    try:
        from db.supabase_client import get_admin_client
        client_sb = get_admin_client()
        if client_sb is None:
            # Infra gap — fail open; handlers are shape-idempotent.
            logger.warning("idempotency skip: no supabase client")
            return False
        client_sb.table("webhook_events").insert({
            "provider": "razorpay",
            "event_id": event_id,
            "event_type": event_type,
        }).execute()
        return False
    except Exception as e:
        # postgrest returns a 409 / "duplicate key" PostgrestAPIError
        # on UNIQUE violation. We can't rely on a typed exception here
        # since supabase-py versions change the class, so match on the
        # error text. Any OTHER error (table missing, auth, network)
        # we fail-open and let the handler run — the downstream writes
        # are shape-idempotent so the outcome is still correct.
        s = str(e).lower()
        if (
            "duplicate key" in s
            or "unique constraint" in s
            or "23505" in s  # Postgres SQLSTATE for unique_violation
            or "already exists" in s
        ):
            logger.info(
                "webhook duplicate suppressed: event_id=%s type=%s",
                event_id, event_type,
            )
            return True
        # Unexpected error — log and proceed with processing.
        logger.warning(
            "idempotency insert failed (proceeding with handler): %s: %s",
            type(e).__name__, e,
        )
        return False


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

    Idempotency:
      - Primary dedup: on-insert UNIQUE(provider, event_id) against
        the `webhook_events` table (migration 002). If the insert
        trips the unique constraint, this is a retry of an event we
        already processed → return 200 OK so Razorpay stops retrying
        and we do NOT re-fire any tier-flip side effects.
      - Secondary safety net: the per-event handlers themselves are
        shape-idempotent (upsert by `razorpay_subscription_id`), so
        if the dedup table is briefly unavailable the tier outcome
        is still correct — we just pay in log noise.

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

    # 2a. Idempotency check. Razorpay retries on any non-2xx / timeout
    # for up to ~24h — without dedup we'd re-fire tier flips, double
    # "demoted to free" logs, and stomp on subscriptions rows. The
    # event-id we store is a provider-natural composite; see
    # _razorpay_event_id below for why it's built this way.
    _dedup_event_id = _razorpay_event_id(payload)
    if _dedup_event_id and _claim_webhook_event(_dedup_event_id, event, logger):
        # Already processed — ack so Razorpay stops retrying.
        return {"ok": True, "duplicate": True, "event": event}

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
