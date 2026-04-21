# backend/routers/payments.py
# Razorpay payment integration for YieldIQ subscriptions.
from __future__ import annotations
import os
import sys
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from backend.middleware.auth import get_current_user

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
if not RAZORPAY_KEY_ID:
    import logging as _rl
    _rl.getLogger("yieldiq.payments").warning("RAZORPAY_KEY_ID not set — payments disabled")


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


@router.post("/verify")
async def verify_payment(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
    plan_id: str = "pro",
    user: dict = Depends(get_current_user),
):
    """Verify Razorpay payment and upgrade user tier."""
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
