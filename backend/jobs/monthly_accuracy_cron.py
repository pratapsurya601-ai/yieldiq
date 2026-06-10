"""monthly_accuracy_cron.py — T5.7 cron entrypoint.

Schedule
────────
1st of every month at 06:00 UTC, via
``.github/workflows/monthly-accuracy-report.yml``.

What it does
────────────
1. Determine the target month (today − 7 days; in the first week of
   the new month this resolves to the previous month).
2. Run ``compute_monthly_accuracy(target_month)``.
3. Persist a JSON + markdown snapshot to disk so the /calibration
   page can link to "latest monthly report" without a DB migration
   (out-of-scope for T5.7 per the brief).
4. Email the operator a markdown summary if SENDGRID_API_KEY and
   OPERATOR_EMAIL are both set; otherwise log + skip.

Usage
─────
    # default — auto-resolve target month, write to /tmp/
    python -m backend.jobs.monthly_accuracy_cron

    # explicit month + custom output dir
    python -m backend.jobs.monthly_accuracy_cron --month 2026-05 \\
        --output-dir /tmp/yieldiq-accuracy

    # skip email send (CI dry-run)
    python -m backend.jobs.monthly_accuracy_cron --no-email

Exit codes
──────────
    0  Success (including the empty-month case — nothing to score).
    1  Unrecoverable error (e.g. invalid --month string).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Make the package importable when run as ``python backend/jobs/...``.
_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services.monthly_accuracy_report import (  # noqa: E402
    compute_monthly_accuracy,
    to_dict,
    to_markdown,
)

logger = logging.getLogger("yieldiq.cron.monthly_accuracy")
logging.basicConfig(
    level=os.environ.get("MONTHLY_ACCURACY_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def resolve_target_month(today: date | None = None) -> str:
    """Today minus 7 days, formatted YYYY-MM.

    On the 1st of June this yields May ("2026-05"). On the 8th of
    June it still yields June ("2026-06"); by design the cron only
    runs on the 1st so this latter case happens only during manual
    dispatches.
    """
    today = today or date.today()
    anchor = today - timedelta(days=7)
    return f"{anchor.year:04d}-{anchor.month:02d}"


def _write_snapshot(output_dir: Path, month_year: str, report) -> tuple[Path, Path]:
    """Write {month}.json and {month}.md plus latest.json + latest.md
    pointers. Returns (json_path, md_path) for the dated files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{month_year}.json"
    md_path = output_dir / f"{month_year}.md"

    json_payload = {
        "schema_version": 1,
        "report": to_dict(report),
    }
    json_path.write_text(
        json.dumps(json_payload, indent=2, default=str),
        encoding="utf-8",
    )
    md_path.write_text(to_markdown(report), encoding="utf-8")

    # "Latest" pointers — overwrite each run. The /calibration page
    # can serve these without knowing the month name.
    (output_dir / "latest.json").write_text(
        json.dumps(json_payload, indent=2, default=str),
        encoding="utf-8",
    )
    (output_dir / "latest.md").write_text(to_markdown(report), encoding="utf-8")

    return json_path, md_path


def _email_operator(report, json_path: Path, md_path: Path) -> bool:
    """Send the markdown summary to OPERATOR_EMAIL. Returns True on
    success, False on any miss (no key, no recipient, send failed).
    Never raises — cron must be fail-quiet on email.
    """
    operator = os.environ.get("OPERATOR_EMAIL", "").strip()
    if not operator:
        logger.info("OPERATOR_EMAIL not set — skipping email")
        return False
    if not os.environ.get("SENDGRID_API_KEY", "").strip():
        logger.info("SENDGRID_API_KEY not set — skipping email")
        return False

    try:
        from backend.services.email_service import send_email  # type: ignore
    except Exception as exc:
        logger.warning("email_service import failed: %s", exc)
        return False

    subject = (
        f"[YieldIQ] Monthly accuracy — {report.report_month} "
        f"({report.direction_accuracy_pct}% direction acc., "
        f"{report.coverage_count}/{report.total_verdicts_published} covered)"
    )
    md = to_markdown(report)
    html = (
        "<pre style=\"font-family:ui-monospace,Menlo,Consolas,monospace;"
        "font-size:12px;line-height:1.5\">"
        f"{md.replace('<', '&lt;').replace('>', '&gt;')}"
        "</pre>"
        "<p style='font-size:11px;color:#6B7280'>"
        f"Snapshot files: {json_path.name}, {md_path.name}"
        "</p>"
    )
    try:
        ok = send_email(
            to_email=operator,
            subject=subject,
            html=html,
            text=md,
            tags=["monthly-accuracy", "operator"],
        )
        if ok:
            logger.info("operator email sent to %s", operator)
        else:
            logger.warning("operator email returned False")
        return bool(ok)
    except Exception as exc:
        logger.warning("operator email raised: %s", exc)
        return False


async def run_monthly_accuracy_job(
    month_year: str | None = None,
    output_dir: str | None = None,
    send_email_flag: bool = True,
) -> dict:
    """Programmatic entrypoint. Returns a small summary dict.

    ``async`` per the brief's signature even though the body is
    sync; FastAPI tests can await it cleanly.
    """
    target = month_year or resolve_target_month()
    out = Path(output_dir or os.environ.get("ACCURACY_OUTPUT_DIR", "/tmp/yieldiq-accuracy"))

    logger.info("computing monthly accuracy for %s", target)
    report = compute_monthly_accuracy(target)

    json_path, md_path = _write_snapshot(out, target, report)
    logger.info(
        "wrote snapshot: %s (%d verdicts, %d covered, %s%% direction acc.)",
        json_path,
        report.total_verdicts_published,
        report.coverage_count,
        report.direction_accuracy_pct,
    )

    emailed = False
    if send_email_flag:
        emailed = _email_operator(report, json_path, md_path)

    return {
        "month": target,
        "total_verdicts": report.total_verdicts_published,
        "coverage": report.coverage_count,
        "direction_accuracy_pct": report.direction_accuracy_pct,
        "median_abs_error_pct": report.median_abs_error_pct,
        "json_path": str(json_path),
        "md_path": str(md_path),
        "emailed": emailed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--month",
        default=None,
        help="Target month YYYY-MM. Defaults to (today - 7 days).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write snapshot JSON + MD. "
             "Defaults to ACCURACY_OUTPUT_DIR env or /tmp/yieldiq-accuracy.",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Skip operator email (useful for CI dry-runs).",
    )
    args = parser.parse_args()

    try:
        import asyncio
        result = asyncio.run(
            run_monthly_accuracy_job(
                month_year=args.month,
                output_dir=args.output_dir,
                send_email_flag=not args.no_email,
            )
        )
    except ValueError as exc:
        logger.error("invalid input: %s", exc)
        return 1
    except Exception as exc:  # pragma: no cover — last-resort guard
        logger.exception("monthly accuracy job crashed: %s", exc)
        return 1

    # Print a one-line operator-friendly summary on stdout so the GH
    # Actions log makes the outcome scannable.
    sys.stdout.write(
        f"monthly_accuracy: month={result['month']} "
        f"total={result['total_verdicts']} coverage={result['coverage']} "
        f"dir_acc={result['direction_accuracy_pct']}% "
        f"median_err={result['median_abs_error_pct']}% "
        f"emailed={result['emailed']}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
