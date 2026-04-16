# payments/razorpay_client.py
# Razorpay SDK wrapper — create subscriptions, verify signatures.
from __future__ import annotations
import os
import razorpay

_client = None


def get_client() -> razorpay.Client:
    """Lazy-init Razorpay client from env vars."""
    global _client
    if _client is None:
        key_id = os.environ.get("RAZORPAY_KEY_ID", "")
        key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
        if not key_id or not key_secret:
            raise RuntimeError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set")
        _client = razorpay.Client(auth=(key_id, key_secret))
    return _client


def get_plan_map() -> dict:
    """Plan IDs from env vars. Keys are (tier, billing) tuples."""
    return {
        ("pro", "monthly"):     os.environ.get("RZP_PLAN_PRO_MONTHLY", ""),
        ("analyst", "monthly"): os.environ.get("RZP_PLAN_ANALYST_MONTHLY", ""),
        # Legacy aliases
        ("starter", "monthly"): os.environ.get("RZP_PLAN_PRO_MONTHLY", ""),
    }


def create_subscription(email: str, tier: str, billing: str = "monthly") -> dict:
    """Create a Razorpay subscription and return the subscription object."""
    plan_map = get_plan_map()
    plan_id = plan_map.get((tier, billing), "")
    if not plan_id:
        raise ValueError(f"No plan ID configured for ({tier}, {billing})")

    client = get_client()
    sub = client.subscription.create({
        "plan_id": plan_id,
        "total_count": 120,  # max billing cycles
        "quantity": 1,
        "notes": {
            "email": email,
            "tier": tier,
            "billing": billing,
            "app": "yieldiq",
        },
    })

    # Store in DB
    from payments.models import insert_subscription
    insert_subscription(
        email=email,
        razorpay_sub_id=sub["id"],
        razorpay_plan_id=plan_id,
        tier=tier,
        amount_paise=sub.get("amount"),
        currency=sub.get("currency", "INR"),
    )
    return sub


def verify_payment_signature(params: dict) -> bool:
    """Verify Razorpay payment signature (client-side callback)."""
    client = get_client()
    try:
        client.utility.verify_payment_signature(params)
        return True
    except razorpay.errors.SignatureVerificationError:
        return False


def verify_webhook_signature(body: str, signature: str) -> bool:
    """Verify Razorpay webhook signature."""
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        return False
    client = get_client()
    try:
        client.utility.verify_webhook_signature(body, signature, secret)
        return True
    except razorpay.errors.SignatureVerificationError:
        return False
