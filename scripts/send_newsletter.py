"""scripts/send_newsletter.py

CLI entry point for the founder-authored weekly newsletter.

Usage
-----
Dry-run (renders HTML to stdout, no SendGrid call, works offline)::

    python scripts/send_newsletter.py \\
        content/newsletter/2026-04-22-week-17-tcs.md --dry-run

Test send to a single address::

    python scripts/send_newsletter.py \\
        content/newsletter/2026-04-22-week-17-tcs.md \\
        --test-email=founder@example.com

Full send to the live subscriber list (requires Supabase creds)::

    python scripts/send_newsletter.py \\
        content/newsletter/2026-04-22-week-17-tcs.md --send

Override recipients with a CSV (one email per line, header optional)::

    python scripts/send_newsletter.py \\
        content/newsletter/2026-04-22-week-17-tcs.md \\
        --send --list-csv=subscribers.csv

Environment
-----------
SENDGRID_API_KEY        required for any actual send
SENDGRID_FROM_EMAIL     defaults to noreply@yieldiq.com
NEWSLETTER_API_BASE     defaults to http://localhost:8000;
                        set to https://api.yieldiq.in in CI
NEWSLETTER_OG_BASE      defaults to https://www.yieldiq.in
                        (Next.js frontend host, not the FastAPI backend)
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from pathlib import Path

# Make the repo root importable when this script is run directly
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("send_newsletter")


# ── Rate limit ───────────────────────────────────────────────────
# SendGrid shared pool tolerates ~30/s on paid plans, but we cap at
# 10/s to stay well within the safety envelope and avoid IP-rep hits.
_SEND_RATE_PER_SEC = 10
_SLEEP_BETWEEN = 1.0 / _SEND_RATE_PER_SEC


def _load_csv_recipients(path: Path) -> list[str]:
    out: list[str] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row:
                continue
            email = row[0].strip()
            if not email or "@" not in email:
                continue
            if email.lower() == "email":
                continue  # header
            out.append(email)
    return out


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Render and send a weekly YieldIQ founder newsletter.",
    )
    p.add_argument(
        "markdown_path",
        help="Path to the weekly markdown post (with frontmatter).",
    )
    mode = p.add_mutually_exclusive_group(required=False)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Render and print the HTML to stdout. No SendGrid call.",
    )
    mode.add_argument(
        "--test-email",
        metavar="ADDRESS",
        help="Send a single preview email to this address.",
    )
    mode.add_argument(
        "--send",
        action="store_true",
        help="Send to every recipient on the live subscriber list.",
    )
    p.add_argument(
        "--list-csv",
        metavar="PATH",
        help="When used with --send, override the Supabase list with a CSV.",
    )
    p.add_argument(
        "--api-base",
        default=None,
        help="Override the public-API base URL used to fetch live data.",
    )
    p.add_argument(
        "--save-html",
        metavar="PATH",
        help="Also write the rendered HTML to this path (handy for review).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    md_path = Path(args.markdown_path)
    if not md_path.exists():
        logger.error("markdown not found: %s", md_path)
        return 2

    # Default to --dry-run if no mode flag was given. Friendlier than
    # silently doing nothing OR accidentally sending to the live list.
    if not (args.dry_run or args.test_email or args.send):
        logger.info("no mode flag given — defaulting to --dry-run")
        args.dry_run = True

    # ── Render ───────────────────────────────────────────────────
    from backend.services.newsletter_render_service import render_weekly_pick

    logger.info("rendering: %s", md_path)
    subject, html = render_weekly_pick(
        md_path,
        api_base=args.api_base,
        recipient_email=args.test_email or "subscriber@yieldiq.in",
    )
    logger.info("subject: %s", subject)
    logger.info("html length: %d chars", len(html))

    if args.save_html:
        out_path = Path(args.save_html)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
        logger.info("wrote rendered HTML to %s", out_path)

    # ── Dry run ──────────────────────────────────────────────────
    if args.dry_run:
        # Print to stdout so the user can pipe to a file or browser.
        print(html)
        logger.info("dry-run complete — no email was sent")
        return 0

    # Anything past this point hits SendGrid.
    if not os.environ.get("SENDGRID_API_KEY"):
        logger.error(
            "SENDGRID_API_KEY is not set — refusing to attempt a real send. "
            "Use --dry-run to preview without credentials."
        )
        return 3

    from backend.services.newsletter_service import (
        send_weekly_pick_to,
        get_weekly_pick_recipients,
    )

    # ── Test single address ──────────────────────────────────────
    if args.test_email:
        ok = send_weekly_pick_to(args.test_email, subject=subject, html=html)
        logger.info("test send to %s: %s", args.test_email, "ok" if ok else "failed")
        return 0 if ok else 1

    # ── Full send ────────────────────────────────────────────────
    if args.list_csv:
        recipients = _load_csv_recipients(Path(args.list_csv))
        logger.info("recipients from CSV %s: %d", args.list_csv, len(recipients))
    else:
        recipients = get_weekly_pick_recipients()
        logger.info("recipients from Supabase: %d", len(recipients))

    if not recipients:
        logger.warning("no recipients — nothing to send")
        return 0

    sent = 0
    failed = 0
    for i, email in enumerate(recipients, start=1):
        try:
            if send_weekly_pick_to(email, subject=subject, html=html):
                sent += 1
            else:
                failed += 1
        except Exception as e:  # never abort the batch on one failure
            logger.warning("send failed for recipient %d: %s", i, e)
            failed += 1
        # Rate limit
        time.sleep(_SLEEP_BETWEEN)
        if i % 50 == 0:
            logger.info("progress: %d/%d sent", i, len(recipients))

    logger.info(
        "send complete: %d sent, %d failed, %d total",
        sent, failed, len(recipients),
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
