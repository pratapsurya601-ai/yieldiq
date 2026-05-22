"""scripts/email_smoke.py — Day-101b email deliverability smoke test.

Sends one of each transactional email type to a recipient you control,
using the same code path the prod app uses. Run AFTER any DNS / sender-
authentication change to verify SPF + DKIM + DMARC actually pass on the
receiving side.

Usage:

    SENDGRID_API_KEY=SG.xxx \
    SENDGRID_FROM_EMAIL=hello@yieldiq.in \
    python scripts/email_smoke.py --to you@gmail.com

After the script completes, open each delivered message in Gmail or
Outlook, view the raw headers ("Show original" in Gmail), and confirm:

    SPF:   PASS  (domain matches the From-header domain)
    DKIM:  PASS  (signing domain matches the From-header domain)
    DMARC: PASS

If any of those are FAIL or NEUTRAL, the DNS change has not yet
propagated or the authenticated domain does not match the From header.
See docs/runbooks/email-deliverability-2026-05-22.md for details.

This script does NOT bump CACHE_VERSION, touch the cache invalidation
manifest, or modify any backend behaviour. It is a read-only sender that
imports the existing email_service functions verbatim so we test the
same code path real users would see.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Callable


def _result(label: str, ok: bool) -> str:
    return f"  [{('OK ' if ok else 'FAIL')}] {label}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--to",
        required=True,
        help="Recipient address you control (Gmail recommended — "
        "easiest 'Show original' viewer).",
    )
    parser.add_argument(
        "--skip",
        default="",
        help="Comma-separated list of types to skip "
        "(welcome,upgrade,student,digest,alert).",
    )
    args = parser.parse_args()

    if not os.environ.get("SENDGRID_API_KEY"):
        print("ERROR: SENDGRID_API_KEY not set in environment.", file=sys.stderr)
        return 2

    from_email = os.environ.get("SENDGRID_FROM_EMAIL", "hello@yieldiq.com")
    print(f"Sending smoke batch from {from_email} -> {args.to}")
    print("(SendGrid response will print per message)\n")

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    results: list[tuple[str, bool]] = []

    # Import locally so import errors are visible on the right line.
    try:
        from backend.services.email_service import (
            send_welcome_email,
            send_upgrade_confirmation_email,
            send_student_application_email,
            send_email,
        )
    except Exception as exc:
        print(f"ERROR: cannot import email_service: {exc}", file=sys.stderr)
        return 3

    def _run(label: str, fn: Callable[[], bool]) -> None:
        if label.split()[0].lower() in skip:
            print(f"  [SKIP] {label}")
            return
        try:
            ok = bool(fn())
        except Exception as exc:
            print(f"  [EXC ] {label}: {exc}")
            results.append((label, False))
            return
        print(_result(label, ok))
        results.append((label, ok))
        # SendGrid free tier is 1 req/sec.
        time.sleep(1.2)

    _run(
        "welcome — send_welcome_email",
        lambda: send_welcome_email(args.to, name="Smoke Test"),
    )
    _run(
        "upgrade — send_upgrade_confirmation_email (analyst)",
        lambda: send_upgrade_confirmation_email(args.to, tier="analyst", name="Smoke Test"),
    )
    _run(
        "student — send_student_application_email (approved)",
        lambda: send_student_application_email(
            args.to, decision="approved", name="Smoke Test"
        ),
    )

    # Band alert template: simulate via the generic send_email surface so we
    # don't depend on a watchlist row existing in Supabase for the test
    # recipient. Same _send_email path, same headers, so deliverability
    # signal is identical.
    _run(
        "alert — generic send_email with band_alert tag",
        lambda: send_email(
            to_email=args.to,
            subject="[smoke] Band alert: TEST.NS crossed the bear band",
            html="<p>This is a deliverability smoke test for the band_alert "
            "template. Ignore the contents.</p>",
            text="Band alert smoke test — ignore.",
            tags=["band_alert"],
        ),
    )

    # Weekly digest: skipped by default because it queries the DB. Run with
    # --skip='' explicitly to include it on a machine with Aiven creds.
    if "digest" not in skip:
        try:
            from backend.services.email_service import send_weekly_digest

            _run("digest — send_weekly_digest", lambda: send_weekly_digest(args.to))
        except Exception as exc:
            print(f"  [SKIP] digest — import / DB unavailable: {exc}")

    print("\nSummary:")
    for label, ok in results:
        print(_result(label, ok))

    print(
        "\nNext: open each delivered message in Gmail, click the triple-dot menu\n"
        "→ 'Show original', and confirm SPF=PASS, DKIM=PASS, DMARC=PASS.\n"
        "Any FAIL/NEUTRAL means DNS has not propagated or the authenticated\n"
        "domain does not match the From header. See\n"
        "docs/runbooks/email-deliverability-2026-05-22.md."
    )

    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
