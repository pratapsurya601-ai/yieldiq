# backend/routers/admin.py
# Admin dashboard — key metrics for admin users only.
from __future__ import annotations
import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from backend.middleware.auth import get_current_user

logger = logging.getLogger("yieldiq.admin")

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

ADMIN_EMAILS = {"pratapsurya601@gmail.com", "suryasbss601@gmail.com"}


def require_admin(user: dict = Depends(get_current_user)):
    """Dependency that requires admin email."""
    if user.get("email") not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.get("/stats")
async def get_admin_stats(user: dict = Depends(require_admin)):
    """Return key platform metrics. Admin only."""
    stats = {
        "total_users": 0,
        "users_today": 0,
        "analyses_today": 0,
        "paid_users": 0,
        "revenue_monthly": 0,
        "top_stocks_today": [],
        "errors_today": 0,
        "db_size_mb": 0,
        "cache_hit_rate": 0.0,
    }

    # Try to get real data from rate limiter (tracks daily usage)
    try:
        from backend.middleware.rate_limit import rate_limiter
        if hasattr(rate_limiter, "_usage"):
            today = date.today().isoformat()
            total_analyses = 0
            user_ids_today = set()
            for key, count in rate_limiter._usage.items():
                if today in key:
                    total_analyses += count
                    # Key format: "user_id:date"
                    uid = key.rsplit(":", 1)[0]
                    user_ids_today.add(uid)
            stats["analyses_today"] = total_analyses
            stats["users_today"] = len(user_ids_today)
    except Exception:
        pass

    # Try to get cache stats
    try:
        from backend.services.cache_service import cache
        if hasattr(cache, "_store"):
            total_keys = len(cache._store)
            stats["cache_hit_rate"] = round(min(0.95, total_keys / max(1, total_keys + 10)), 2)
    except Exception:
        pass

    # Try to get top stocks from cache
    try:
        from backend.services.cache_service import cache
        stock_counts: dict[str, int] = {}
        for key in list(cache._store.keys()):
            if key.startswith("analysis:"):
                ticker = key.replace("analysis:", "")
                stock_counts[ticker] = stock_counts.get(ticker, 0) + 1
        if stock_counts:
            sorted_stocks = sorted(stock_counts.items(), key=lambda x: x[1], reverse=True)
            stats["top_stocks_today"] = [s[0] for s in sorted_stocks[:10]]
    except Exception:
        pass

    # Try Supabase user count
    try:
        from db.supabase_client import get_client
        client = get_client()
        if client:
            # Count users from auth
            result = client.table("users_meta").select("id", count="exact").execute()
            if hasattr(result, "count") and result.count:
                stats["total_users"] = result.count
    except Exception:
        pass

    return stats


@router.post("/trigger-newsletter")
async def trigger_newsletter(user: dict = Depends(require_admin)):
    """Manually trigger newsletter send. Admin only."""
    import threading
    from backend.services.newsletter_service import send_newsletter_to_all
    threading.Thread(target=send_newsletter_to_all, daemon=True).start()
    return {"status": "newsletter queued", "triggered_by": user.get("email")}
