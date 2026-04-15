"""
Seed the ``fair_value_history`` table by hitting the live analysis
endpoint for a curated list of 50 popular tickers. Each successful
call triggers ``store_today_fair_value()`` inside AnalysisService,
which writes one row (or upserts today's row) per ticker.

Usage:
    # Recommended — Railway's env (JWT_SECRET + live DB):
    railway run python scripts/seed_fv_history.py

    # Or with a pre-generated service token:
    SERVICE_WARMUP_TOKEN="<jwt>" python scripts/seed_fv_history.py

    # Point at a different backend (default: api.yieldiq.in):
    BACKEND_URL="http://localhost:8000" python scripts/seed_fv_history.py

You'll need SERVICE_WARMUP_TOKEN or JWT_SECRET available. The token
can be generated with scripts/generate_service_token.py.
"""
from __future__ import annotations

import os
import sys
import time

import requests


TICKERS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ITC",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "BAJFINANCE",
    "AXISBANK", "MARUTI", "TITAN", "SUNPHARMA", "WIPRO",
    "HCLTECH", "NESTLEIND", "ULTRACEMCO", "ASIANPAINT", "ICICIBANK",
    "DIVISLAB", "DRREDDY", "CIPLA", "EICHERMOT", "BAJAJFINSV",
    "COALINDIA", "ONGC", "NTPC", "POWERGRID", "ADANIPORTS",
    "HINDUNILVR", "TATACONSUM", "BRITANNIA", "DABUR", "MARICO",
    "COLPAL", "PIDILITIND", "BAJAJ-AUTO", "HEROMOTOCO", "M&M",
    "TATAPOWER", "TATASTEEL", "JSWSTEEL", "HINDALCO", "IOC",
    "BPCL", "GAIL", "IRCTC", "INDIGO", "DLF",
]


def _resolve_token() -> str:
    """Read a JWT from env, or generate one on the fly if JWT_SECRET is set."""
    tok = os.environ.get("SERVICE_WARMUP_TOKEN")
    if tok:
        return tok

    secret = os.environ.get("JWT_SECRET") or os.environ.get("YIELDIQ_JWT_SECRET")
    if not secret:
        print(
            "ERROR: set SERVICE_WARMUP_TOKEN, or run with JWT_SECRET available "
            "(via `railway run` or an .env file)."
        )
        sys.exit(1)

    # Generate a short-lived pro-tier token in-process so the script
    # is self-contained when run with railway's secret.
    from datetime import datetime, timedelta
    from jose import jwt

    token = jwt.encode(
        {
            "sub": "seed-fv-history",
            "email": "seed@yieldiq.internal",
            "tier": "pro",
            "exp": datetime.utcnow() + timedelta(hours=1),
            "iat": datetime.utcnow(),
        },
        secret,
        algorithm="HS256",
    )
    return token


def main() -> int:
    backend = os.environ.get("BACKEND_URL", "https://api.yieldiq.in").rstrip("/")
    token = _resolve_token()
    headers = {"Authorization": f"Bearer {token}"}

    print(f"Seeding {len(TICKERS)} tickers against {backend}")
    print(f"{'TICKER':<14} {'STATUS':<8} {'FV':>14} {'VERDICT':>14}")
    print("-" * 56)

    ok = failed = 0
    for t in TICKERS:
        symbol = f"{t}.NS"
        url = f"{backend}/api/v1/analysis/{symbol}"
        try:
            resp = requests.get(url, headers=headers, timeout=60)
        except requests.RequestException as exc:
            print(f"{t:<14} {'ERR':<8} {'—':>14} {str(exc)[:14]:>14}")
            failed += 1
            time.sleep(2)
            continue

        status = resp.status_code
        if status == 200:
            try:
                data = resp.json()
                valuation = data.get("valuation") or {}
                fv = valuation.get("fair_value") or 0
                verdict = valuation.get("verdict") or "—"
                print(f"{t:<14} {status:<8} {f'₹{fv:,.2f}':>14} {verdict:>14}")
                ok += 1
            except Exception:
                print(f"{t:<14} {status:<8} {'parse err':>14} {'—':>14}")
                failed += 1
        else:
            # Try to surface the error note if present
            try:
                body = resp.json()
                detail = body.get("detail") if isinstance(body, dict) else None
                err = (
                    (detail.get("error") if isinstance(detail, dict) else detail)
                    or f"HTTP {status}"
                )
            except Exception:
                err = f"HTTP {status}"
            print(f"{t:<14} {status:<8} {'—':>14} {str(err)[:14]:>14}")
            failed += 1

        # Be kind to the backend — 3s between requests avoids
        # spiking rate-limit counters and gives yfinance breathing room.
        time.sleep(3)

    print("-" * 56)
    print(f"Summary: {ok} OK, {failed} failed, {len(TICKERS)} total")

    # Optional DB verification — only if DATABASE_URL is set.
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        print("\n=== fair_value_history verification ===")
        try:
            # Normalise Aiven's postgres:// → postgresql:// for SQLA 2.x
            if db_url.startswith("postgres://"):
                db_url = "postgresql://" + db_url[len("postgres://"):]
            from sqlalchemy import create_engine, text
            engine = create_engine(db_url)
            with engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT ticker, COUNT(*) AS rows,
                           MAX(updated_at)::date AS latest
                    FROM fair_value_history
                    GROUP BY ticker
                    ORDER BY ticker
                """)).fetchall()
            if not rows:
                print("(no rows — table empty or not created yet)")
            else:
                print(f"{'TICKER':<14} {'ROWS':>6} {'LATEST':>12}")
                for r in rows:
                    print(f"{r[0]:<14} {r[1]:>6} {str(r[2]):>12}")
        except Exception as exc:
            print(f"DB verification failed: {exc}")
    else:
        print(
            "\nSkipped DB verification (DATABASE_URL not set). Run "
            "`railway run python scripts/seed_fv_history.py` to see "
            "the row count afterwards."
        )

    return 0 if ok > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
