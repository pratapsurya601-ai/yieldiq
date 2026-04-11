# payments/webhook_server.py
# FastAPI webhook receiver for Razorpay subscription events.
# Runs alongside Streamlit via supervisord.
from __future__ import annotations
import os
import sys
import json
import logging

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

# Add project root to path so we can import dashboard modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from payments.razorpay_client import verify_webhook_signature
from payments.models import update_subscription_status, init_subscriptions_table

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yieldiq.webhook")

app = FastAPI(title="YieldIQ Webhook Server", docs_url=None, redoc_url=None)


def _set_user_tier(email: str, tier: str) -> None:
    """Update user tier in auth.db."""
    import sqlite3
    from pathlib import Path
    db_path = Path(os.environ.get("YIELDIQ_DATA_DIR", str(Path(__file__).resolve().parent.parent / "dashboard"))) / "auth.db"
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "UPDATE users SET tier = ?, updated_at = datetime('now') WHERE email = ?",
            (tier, email),
        )
        conn.commit()
        conn.close()
        logger.info(f"Tier updated: {email} → {tier}")
    except Exception as e:
        logger.error(f"Failed to update tier for {email}: {e}")


@app.on_event("startup")
async def startup():
    init_subscriptions_table()
    logger.info("Webhook server started — subscriptions table ready")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "yieldiq-webhook"}


@app.post("/webhook/razorpay")
async def razorpay_webhook(request: Request):
    """Handle Razorpay subscription lifecycle webhooks."""
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    # Verify signature
    if not verify_webhook_signature(body.decode("utf-8"), signature):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event", "")
    entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
    sub_id = entity.get("id", "")
    payment_id = payload.get("payload", {}).get("payment", {}).get("entity", {}).get("id")
    notes = entity.get("notes", {})
    email = notes.get("email", "")
    tier = notes.get("tier", "")

    logger.info(f"Webhook: {event} | sub={sub_id} | email={email} | tier={tier}")

    if event == "subscription.authenticated":
        # Subscription authorized but not yet charged
        update_subscription_status(sub_id, "authenticated", payment_id)

    elif event == "subscription.activated":
        # First payment done — upgrade tier
        found_email = update_subscription_status(sub_id, "active", payment_id)
        if found_email and tier:
            _set_user_tier(found_email, tier)
        elif email and tier:
            _set_user_tier(email, tier)

    elif event == "subscription.charged":
        # Recurring payment success — ensure tier stays active
        found_email = update_subscription_status(sub_id, "active", payment_id)
        if found_email and tier:
            _set_user_tier(found_email, tier)

    elif event == "subscription.halted":
        # Payment failures — downgrade to free
        found_email = update_subscription_status(sub_id, "halted")
        if found_email:
            _set_user_tier(found_email, "free")
            logger.warning(f"Subscription halted — downgraded {found_email} to free")

    elif event == "subscription.cancelled":
        # User cancelled — downgrade to free
        current_end = entity.get("current_end")
        found_email = update_subscription_status(sub_id, "cancelled", current_end=str(current_end) if current_end else None)
        if found_email:
            _set_user_tier(found_email, "free")
            logger.info(f"Subscription cancelled — downgraded {found_email} to free")

    elif event == "subscription.expired":
        found_email = update_subscription_status(sub_id, "expired")
        if found_email:
            _set_user_tier(found_email, "free")

    else:
        logger.info(f"Unhandled event: {event}")

    return JSONResponse({"status": "ok"})
