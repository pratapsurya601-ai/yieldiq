"""
Generate a long-lived service JWT for the cache-warmup cron.

The token never expires (well, 100 years — far enough). Keep it
in GitHub repo secrets as SERVICE_WARMUP_TOKEN so
.github/workflows/cache_warmup.yml can authenticate cron requests
to /api/v1/analysis/{ticker}.

The token uses tier="pro" (rate-limit bucket of 999999/day) and a
dedicated user_id so its rate usage doesn't mix with real users.

Usage (recommended — uses Railway's live JWT_SECRET):
    railway run python scripts/generate_service_token.py

Usage (local, if you have JWT_SECRET in .env):
    JWT_SECRET="..." python scripts/generate_service_token.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta


def main() -> int:
    try:
        from jose import jwt
    except ImportError:
        print("ERROR: python-jose is not installed.")
        print("Run: pip install 'python-jose[cryptography]'")
        return 1

    secret = (
        os.environ.get("JWT_SECRET")
        or os.environ.get("YIELDIQ_JWT_SECRET")
    )
    if not secret:
        print("ERROR: JWT_SECRET (or YIELDIQ_JWT_SECRET) is not set.")
        print()
        print("Option A — use Railway's live secret:")
        print("  railway run python scripts/generate_service_token.py")
        print()
        print("Option B — pass it inline:")
        print('  JWT_SECRET="..." python scripts/generate_service_token.py')
        return 1

    # 100-year expiry — effectively non-expiring but still a valid JWT.
    # Revocable by rotating JWT_SECRET if compromised.
    expires = datetime.utcnow() + timedelta(days=365 * 100)

    payload = {
        "sub": "service-warmup",
        "email": "service-warmup@yieldiq.internal",
        "tier": "pro",
        "exp": expires,
        "iat": datetime.utcnow(),
    }

    token = jwt.encode(payload, secret, algorithm="HS256")

    print()
    print("=" * 72)
    print("SERVICE_WARMUP_TOKEN")
    print("=" * 72)
    print(token)
    print("=" * 72)
    print(f"Subject: service-warmup")
    print(f"Tier:    pro (999999 req/day)")
    print(f"Expires: {expires.isoformat()}Z")
    print()
    print("Add to GitHub repo → Settings → Secrets and variables →")
    print("Actions → New repository secret:")
    print("  Name:  SERVICE_WARMUP_TOKEN")
    print("  Value: <paste the token above>")
    print()
    print("To rotate: regenerate with a new JWT_SECRET (this invalidates")
    print("all existing tokens including real users) — only do this if")
    print("the token is compromised.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
