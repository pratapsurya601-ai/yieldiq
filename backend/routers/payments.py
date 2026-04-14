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

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_ScvhGo30dfN6Ec")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")


@router.get("/debug")
async def payment_debug():
    """Check if Razorpay keys are configured (does NOT expose secrets)."""
    return {
        "key_id": RAZORPAY_KEY_ID[:12] + "..." if RAZORPAY_KEY_ID else "NOT SET",
        "secret_configured": bool(RAZORPAY_KEY_SECRET and len(RAZORPAY_KEY_SECRET) > 5),
        "secret_length": len(RAZORPAY_KEY_SECRET) if RAZORPAY_KEY_SECRET else 0,
        "mode": "test" if "test" in RAZORPAY_KEY_ID else "live" if "live" in RAZORPAY_KEY_ID else "unknown",
    }

PLANS = {
    "starter": {
        "name": "Starter Plan",
        "amount": 49900,  # ₹499 in paise
        "currency": "INR",
        "description": "50 analyses/day, scenarios, screener, PDF reports",
    },
    "pro": {
        "name": "Pro Plan",
        "amount": 199900,  # ₹1,999 in paise
        "currency": "INR",
        "description": "Unlimited analyses, Monte Carlo, all features",
    },
}


@router.get("/plans")
async def get_plans():
    """Get available subscription plans."""
    return {
        "plans": [
            {"id": "starter", **PLANS["starter"], "display_price": "₹499/mo"},
            {"id": "pro", **PLANS["pro"], "display_price": "₹1,999/mo"},
        ],
        "key_id": RAZORPAY_KEY_ID,
    }


@router.post("/create-order")
async def create_order(
    plan_id: str = "starter",
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
    plan_id: str = "starter",
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
        new_tier = plan_id if plan_id in ("starter", "pro") else "starter"

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
