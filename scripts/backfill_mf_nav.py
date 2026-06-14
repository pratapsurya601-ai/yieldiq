"""Operator-run 10-year MF NAV backfill.

LOCAL ONLY — per project discipline (memory/feedback_yieldiq_discipline.md
rule 3), long-running ingest jobs do NOT run inside the Railway worker
and are not wired into a GitHub Actions cron either. The agent does
NOT run this script; it is invoked by the operator on their local
machine against DATABASE_URL pointed at Neon.

What it does
============
For each scheme in scripts/canary_funds_50.json (or --schemes path),
pulls the historical NAV via AMFI's date-ranged endpoint in ~90-day
windows and bulk-COPYs into fund_nav_history. Checkpoint state is
written to scripts/snapshots/backfill_mf_nav_checkpoint.json so the
script can resume after Ctrl-C or transient network failures.

Endpoint
========
AMFI publishes per-scheme NAV history at:

    https://www.amfiindia.com/modules/NavHistoryPeriod
        ?frmdt=DD-Mon-YYYY&todt=DD-Mon-YYYY&mf=<AMC_id>&scheme=<scheme_code>

Some operators prefer the cleaner third-party mirror at:

    https://api.mfapi.in/mf/<scheme_code>

mfapi.in is faster and cleaner (returns JSON), but the script defaults
to the AMFI endpoint to keep us on the official source. Pass
``--source mfapi`` to switch to the mirror for speed during operator
testing.

Throttling
==========
800ms sleep between requests per AMFI's polite-use guidance. With
~6,000 schemes × ~40 windows for 10y = 240k requests total at 800ms
each = ~53 hours of wall-clock for the full universe. The default
canary set of 50 schemes runs in ~30 minutes.

Dependency: funds table must be populated first
================================================
fund_nav_history rows reference funds.scheme_code (logical FK enforced
by the upsert path in amfi_nav.py). The backfill aborts early if the
funds table is empty. Two ways to satisfy the dependency:

  1. Run the scheme-master ingest yourself, then rerun the backfill:

       PYTHONPATH=. python -m data_pipeline.sources.amfi_scheme_master
       python scripts/backfill_mf_nav.py

  2. Pass ``--auto-bootstrap`` to have the backfill run the
     scheme-master ingest in-process before pulling NAV history.

Note: invoking ``python -m data_pipeline.sources.amfi_scheme_master``
directly requires ``PYTHONPATH=.`` (the repo has no pyproject.toml /
setup.py). The two cron workflows set this in their env block.

Usage
=====
    # Top-50 canary set (operator default for first run):
    DATABASE_URL=postgres://... python scripts/backfill_mf_nav.py

    # First-time setup — populate funds, then backfill NAV:
    DATABASE_URL=postgres://... python scripts/backfill_mf_nav.py \\
        --auto-bootstrap

    # Full universe (operator only, when ready for the long haul):
    DATABASE_URL=postgres://... python scripts/backfill_mf_nav.py \\
        --schemes-source funds_table --years 10

    # Resume after interruption:
    DATABASE_URL=postgres://... python scripts/backfill_mf_nav.py --resume
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# Allow running as a script from anywhere in the repo.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logger = logging.getLogger("backfill_mf_nav")

REPO_ROOT = Path(__file__).resolve().parent.parent
CANARY_FUNDS_JSON = REPO_ROOT / "scripts" / "canary_funds_50.json"
CHECKPOINT_PATH = REPO_ROOT / "scripts" / "snapshots" / "backfill_mf_nav_checkpoint.json"

AMFI_HISTORY_URL = (
    "https://www.amfiindia.com/modules/NavHistoryPeriod"
    "?frmdt={frm}&todt={to}&mf=0&scheme={scheme}"
)
MFAPI_URL = "https://api.mfapi.in/mf/{scheme}"

WINDOW_DAYS = 90
DEFAULT_THROTTLE = 0.8  # 800ms — AMFI polite-use guidance


def _amfi_date(d: date) -> str:
    return d.strftime("%d-%b-%Y")


def _load_canary_schemes() -> list[str]:
    data = json.loads(CANARY_FUNDS_JSON.read_text(encoding="utf-8"))
    seen: set[str] = set()
    out: list[str] = []
    for row in data["schemes"]:
        sc = row["scheme_code"]
        if sc not in seen:
            seen.add(sc)
            out.append(sc)
    return out


def _funds_row_count(db_url: str) -> int:
    """Return COUNT(*) from the funds table."""
    import psycopg2
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM funds")
            return int(cur.fetchone()[0])
    finally:
        conn.close()


def _run_scheme_master_ingest() -> int:
    """Invoke the AMFI scheme-master ingest in-process.

    Returns the exit code from its main(). Used by --auto-bootstrap so
    the operator can populate the funds table without leaving the
    backfill invocation.
    """
    from data_pipeline.sources import amfi_scheme_master
    logger.info("Bootstrapping funds table via amfi_scheme_master ...")
    # Pass an empty argv so the scheme-master CLI does not try to
    # parse this script's flags.
    rc = amfi_scheme_master.main([])
    if rc != 0:
        logger.error("amfi_scheme_master exited with code %d", rc)
    return rc or 0


def _load_funds_table_schemes(db_url: str, skip_existing: bool = False) -> list[str]:
    """All active scheme_codes from the funds table.

    Used when the operator runs the full-universe backfill. Requires
    that amfi_scheme_master has been run at least once.

    When ``skip_existing`` is set, schemes that already have at least one
    row in ``fund_nav_history`` are excluded. This makes a re-dispatch of
    the (350-min-capped) CI backfill resume across runs WITHOUT depending
    on the local checkpoint file — the GH Actions cache that was meant to
    carry the checkpoint does not survive a timeout-cancellation, so a
    naive ``--resume`` would restart from scheme 1 and redo everything
    already done (quadratic waste over successive runs). The DB itself is
    the source of truth for "what's done", so every dispatch processes
    only net-new schemes. The NOT EXISTS is one index probe per fund
    (index on fund_nav_history(scheme_code, nav_date)), so the filter is
    cheap even though fund_nav_history holds tens of millions of rows.

    Note: a scheme mfapi has no data for stays selected every run (it
    never gets a row), so it's re-attempted each dispatch — a small fixed
    set of single cheap calls, not worth tracking separately.
    """
    import psycopg2
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            if skip_existing:
                cur.execute(
                    "SELECT f.scheme_code FROM funds f "
                    "WHERE f.is_active = TRUE "
                    "AND NOT EXISTS ("
                    "    SELECT 1 FROM fund_nav_history h "
                    "    WHERE h.scheme_code = f.scheme_code"
                    ") "
                    "ORDER BY f.scheme_code"
                )
            else:
                cur.execute(
                    "SELECT scheme_code FROM funds WHERE is_active = TRUE "
                    "ORDER BY scheme_code"
                )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        try:
            return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_checkpoint(state: dict) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def _fetch_mfapi_history(scheme_code: str, timeout: int = 30) -> list[dict]:
    """Fetch full history via mfapi.in (one JSON blob per scheme).

    Returns a list of {scheme_code, nav_date, nav} dicts. Empty on error.
    """
    import requests
    try:
        r = requests.get(MFAPI_URL.format(scheme=scheme_code), timeout=timeout)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        logger.warning("mfapi %s: %s", scheme_code, e)
        return []
    data = payload.get("data") or []
    out: list[dict] = []
    for row in data:
        try:
            nav = float(row["nav"])
        except (KeyError, ValueError, TypeError):
            continue
        if nav <= 0:
            continue
        try:
            nav_date = datetime.strptime(row["date"], "%d-%m-%Y").date()
        except (KeyError, ValueError):
            continue
        out.append({"scheme_code": scheme_code, "nav_date": nav_date, "nav": nav})
    return out


def _bulk_upsert(rows: list[dict], conn) -> int:
    """Bulk UPSERT NAV rows. Shares SQL with amfi_nav.UPSERT_SQL."""
    from data_pipeline.sources.amfi_nav import upsert_nav_rows
    return upsert_nav_rows(rows, conn)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--schemes-source", choices=["canary", "funds_table"],
                   default="canary",
                   help="canary = scripts/canary_funds_50.json (default), "
                        "funds_table = all active rows from funds table.")
    p.add_argument("--source", choices=["amfi", "mfapi"], default="mfapi",
                   help="History endpoint. Default mfapi is faster; switch "
                        "to amfi to stay on the official source.")
    p.add_argument("--years", type=int, default=10,
                   help="History depth in years (used only by amfi source).")
    p.add_argument("--throttle", type=float, default=DEFAULT_THROTTLE,
                   help="Sleep between scheme requests (seconds).")
    p.add_argument("--resume", action="store_true",
                   help="Skip schemes already in the checkpoint file.")
    p.add_argument("--skip-existing", action="store_true",
                   help="funds_table only: skip schemes that already have "
                        "NAV rows in the DB. DB-driven resume — survives a "
                        "timed-out CI run whose checkpoint cache was lost, "
                        "so each re-dispatch does only net-new work.")
    p.add_argument("--auto-bootstrap", action="store_true",
                   help="If the funds table is empty, run the AMFI "
                        "scheme-master ingest in-process before the NAV "
                        "backfill. Without this flag, an empty funds "
                        "table aborts the run with an actionable error.")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch only; do not write to DB.")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db_url = os.environ.get("DATABASE_URL")
    if not db_url and not args.dry_run:
        logger.error("DATABASE_URL required (or use --dry-run).")
        return 2
    if db_url and db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]

    # Dependency: funds must be populated. fund_nav_history rows
    # reference funds.scheme_code (logical FK enforced by the upsert
    # path). If the table is empty, abort with an actionable message —
    # or auto-bootstrap the scheme-master ingest if the operator opted
    # in.
    if db_url:
        funds_n = _funds_row_count(db_url)
        if funds_n == 0:
            if args.auto_bootstrap:
                rc = _run_scheme_master_ingest()
                if rc != 0:
                    return rc
                funds_n = _funds_row_count(db_url)
                if funds_n == 0:
                    logger.error(
                        "auto-bootstrap completed but funds is still empty; "
                        "check amfi_scheme_master logs above."
                    )
                    return 2
                logger.info("auto-bootstrap populated %d funds rows", funds_n)
            else:
                logger.error(
                    "ERROR: funds table empty. Run "
                    "'PYTHONPATH=. python -m data_pipeline.sources.amfi_scheme_master' "
                    "first (or rerun this script with --auto-bootstrap)."
                )
                return 2

    if args.schemes_source == "canary":
        schemes = _load_canary_schemes()
    else:
        schemes = _load_funds_table_schemes(db_url, skip_existing=args.skip_existing)
    logger.info("Backfill universe: %d schemes (source=%s, skip_existing=%s)",
                len(schemes), args.schemes_source, args.skip_existing)

    checkpoint = _load_checkpoint() if args.resume else {}
    done: set[str] = set(checkpoint.get("done", []))

    conn = None
    if not args.dry_run:
        import psycopg2
        conn = psycopg2.connect(db_url)

    total_rows = 0
    try:
        for i, sc in enumerate(schemes, 1):
            if sc in done:
                continue
            if args.source == "mfapi":
                rows = _fetch_mfapi_history(sc)
            else:
                # AMFI date-ranged loop — implement in future operator
                # iteration if mfapi proves insufficient. For Phase 1
                # canary scope, mfapi is the recommended path.
                logger.error(
                    "amfi date-ranged endpoint not implemented in Phase 1 "
                    "backfill — use --source mfapi for the canary run."
                )
                return 2

            if args.dry_run:
                logger.info("[%d/%d] %s: %d rows (dry-run)",
                            i, len(schemes), sc, len(rows))
            elif rows:
                n = _bulk_upsert(rows, conn)
                total_rows += n
                logger.info("[%d/%d] %s: upserted %d NAV rows",
                            i, len(schemes), sc, n)
            else:
                logger.warning("[%d/%d] %s: zero rows", i, len(schemes), sc)

            done.add(sc)
            checkpoint["done"] = sorted(done)
            checkpoint["last_run_at"] = datetime.utcnow().isoformat()
            _save_checkpoint(checkpoint)
            time.sleep(args.throttle)
    except KeyboardInterrupt:
        logger.warning("Interrupted — partial backfill committed; "
                       "rerun with --resume to continue.")
    finally:
        if conn is not None:
            conn.close()

    logger.info("Done. schemes=%d rows_upserted=%d", len(done), total_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
