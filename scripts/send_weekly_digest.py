"""scripts/send_weekly_digest.py

Weekly digest CLI / GitHub Actions entry point.

Runs once per week (Thursday 09:00 IST) from the
.github/workflows/weekly_digest_thursday.yml workflow. Iterates
eligible users and calls weekly_digest_service.generate_digest +
email_service.send_email per user.

Why Thursday (not Monday or Sunday):
  - Sunday IST is poor for India retail — users associate Sunday
    with family time, not investing, and unsubscribe rates spike.
  - Monday morning gets buried under the work-week start.
  - Thursday gets opened before the weekend, when users have time
    to actually act on what they read.

Why GitHub Actions (not Railway APScheduler):
  - APScheduler ran inside each uvicorn worker -> 4x duplicate sends
    on Apr-27. GitHub Actions runs exactly once on a guaranteed
    schedule, on infra we don't pay for.

Eligibility:
  - User created >= 7 days ago (don't email day-1 signups twice —
    the welcome email already covered them).
  - user_metadata.weekly_digest_unsubscribed != true
  - users_meta.email_opted_out is not true (existing global opt-out)

Usage
-----
Dry run (renders for one email, no SendGrid call)::

    python scripts/send_weekly_digest.py --dry-run --test-email=you@example.com

Live run::

    python scripts/send_weekly_digest.py --send
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Repo root on path so `backend.*` imports resolve when invoked as a script
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("send_weekly_digest")

# Conservative throttle — SendGrid free tier is 100/day, so even at
# 10 emails/sec we're fine, but slower keeps IP reputation steady.
_SLEEP_BETWEEN_SENDS = 0.5


def _eligible_recipients() -> list[str]:
    """Return emails eligible for the weekly digest.

    Filters:
      - created_at <= now - 7 days   (welcome email handled day 0)
      - users_meta.email_opted_out is not true
      - user_metadata.weekly_digest_unsubscribed is not true
    """
    try:
        from db.supabase_client import get_admin_client
    except Exception as exc:
        log.error("Could not import supabase client: %s", exc)
        return []

    client = get_admin_client()
    if client is None:
        log.error("Supabase admin client unavailable")
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    # Step 1: pull all auth users, then filter in-memory. The Supabase
    # python SDK's admin.list_users() doesn't support a server-side
    # created_at filter, but this is fine while we're sub-10k users.
    users: list[dict] = []
    try:
        # admin.list_users returns User objects; iterate up to a few
        # pages defensively.
        page = 1
        while True:
            resp = client.auth.admin.list_users(page=page, per_page=200)
            batch = resp if isinstance(resp, list) else getattr(resp, "users", [])
            if not batch:
                break
            for u in batch:
                email = getattr(u, "email", None)
                created_at = getattr(u, "created_at", None)
                meta = getattr(u, "user_metadata", {}) or {}
                if not email:
                    continue
                # created_at is ISO 8601 from Supabase
                if isinstance(created_at, str) and created_at > cutoff:
                    continue  # too new — skip
                if meta.get("weekly_digest_unsubscribed") is True:
                    continue
                users.append({"email": email})
            if len(batch) < 200:
                break
            page += 1
            if page > 50:  # paranoid cap
                break
    except Exception as exc:
        log.warning("admin.list_users failed: %s — falling back to users_meta", exc)

    # Step 2: also exclude anyone with the legacy global email_opted_out flag.
    opted_out: set[str] = set()
    try:
        r = (
            client.table("users_meta")
            .select("email,email_opted_out")
            .eq("email_opted_out", True)
            .execute()
        )
        opted_out = {row["email"] for row in (r.data or []) if row.get("email")}
    except Exception as exc:
        log.debug("users_meta opt-out fetch failed: %s", exc)

    eligible = [u["email"] for u in users if u["email"] not in opted_out]
    log.info("Eligible recipients: %d (raw users=%d, opted_out=%d)",
             len(eligible), len(users), len(opted_out))
    return eligible


def _send_one(email: str, dry_run: bool) -> bool:
    from backend.services.weekly_digest_service import generate_digest
    from backend.services.email_service import send_email

    d = generate_digest(email)
    if dry_run:
        log.info("[DRY] would send to %s -- subject=%r html=%d bytes text=%d bytes",
                 email, d.subject, len(d.html), len(d.text))
        return True
    return send_email(
        to_email=email,
        subject=d.subject,
        html=d.html,
        text=d.text,
        tags=["weekly_digest"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send YieldIQ weekly digest")
    parser.add_argument("--dry-run", action="store_true",
                        help="render but do not send")
    parser.add_argument("--send", action="store_true",
                        help="actually send (required for live run)")
    parser.add_argument("--test-email", default="",
                        help="send only to this address (skips eligibility)")
    args = parser.parse_args(argv)

    if not args.send and not args.dry_run:
        parser.error("Pass --dry-run or --send")

    if args.test_email:
        emails = [args.test_email.strip()]
        log.info("Test send to %s", emails[0])
    else:
        emails = _eligible_recipients()

    if not emails:
        log.info("No recipients — nothing to do")
        return 0

    sent = 0
    failed = 0
    for email in emails:
        try:
            ok = _send_one(email, dry_run=args.dry_run)
            if ok:
                sent += 1
            else:
                failed += 1
        except Exception as exc:
            log.exception("send failed for %s: %s", email, exc)
            failed += 1
        time.sleep(_SLEEP_BETWEEN_SENDS)

    log.info("Weekly digest summary: sent=%d failed=%d total=%d",
             sent, failed, len(emails))

    # Exit non-zero only if EVERY send failed (likely a config issue).
    if sent == 0 and failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
