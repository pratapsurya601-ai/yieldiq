"""Diff a current MF canary snapshot against a prior snapshot.

Mirrors scripts/canary_diff.py for the mutual-fund pipeline. Phase 1
scope is data-foundation only — there is no compute cache to gate yet,
so this is a STAGED harness: it produces the diff report and exits
with status 0 on data-plumbing health (current snapshot has the
expected scheme count, NAV freshness within tolerance) regardless of
trailing-return drift. Phase 2 will tighten the gates as compute
lands.

Usage::

    DATABASE_URL=... python scripts/canary_diff_funds.py \\
        --before scripts/snapshots/funds_snapshot_<before>.json \\
        --after  scripts/snapshots/funds_snapshot_<after>.json

If --after is omitted, the latest funds_snapshot_*.json is used.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = REPO_ROOT / "scripts" / "snapshots"

# Phase 1 health thresholds. Loose by design — tightened in Phase 2.
MAX_NAV_STALENESS_DAYS = 5      # latest NAV should be within 5 calendar days
MIN_SCHEMES_PRESENT_PCT = 0.90  # >=90% of canary set must have a latest NAV
DRIFT_RETURN_PP_WARN = 5.0      # >5pp trailing-return drift → log as advisory


def _latest_snapshot() -> Path | None:
    if not SNAPSHOT_DIR.exists():
        return None
    candidates = sorted(SNAPSHOT_DIR.glob("funds_snapshot_*.json"))
    return candidates[-1] if candidates else None


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _index(rows: list[dict]) -> dict[str, dict]:
    return {r["scheme_code"]: r for r in rows}


def _staleness_days(snapshot: dict) -> int | None:
    snap_at = snapshot.get("snapshot_at")
    rows = snapshot.get("rows", [])
    dates = [r.get("latest_nav_date") for r in rows if r.get("latest_nav_date")]
    if not dates or not snap_at:
        return None
    latest = max(dates)
    if isinstance(latest, str):
        latest = _dt.date.fromisoformat(latest[:10])
    snap_d = _dt.datetime.fromisoformat(snap_at.replace("Z", "+00:00")).date()
    return (snap_d - latest).days


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--before", type=Path, default=None,
                   help="Prior snapshot to diff against. Optional — if "
                        "omitted, only health checks run on --after.")
    p.add_argument("--after", type=Path, default=None,
                   help="Current snapshot. Defaults to the newest "
                        "funds_snapshot_*.json in scripts/snapshots/.")
    p.add_argument("--report", default="canary_funds_report.json")
    args = p.parse_args(argv)

    after_path = args.after or _latest_snapshot()
    if after_path is None or not after_path.exists():
        print("ERROR: no --after snapshot found.", file=sys.stderr)
        return 2

    after = _load(after_path)
    after_rows = after.get("rows", [])
    n_total = len(after_rows)
    n_present = sum(1 for r in after_rows if r.get("latest_nav") is not None)

    health: dict = {
        "snapshot_path": str(after_path),
        "scheme_count": n_total,
        "schemes_with_latest_nav": n_present,
        "pct_present": round(n_present / max(1, n_total), 4),
        "staleness_days": _staleness_days(after),
    }
    gate_failures: list[str] = []
    if health["pct_present"] < MIN_SCHEMES_PRESENT_PCT:
        gate_failures.append(
            f"only {n_present}/{n_total} schemes have a latest NAV "
            f"(below {MIN_SCHEMES_PRESENT_PCT:.0%})"
        )
    stale = health["staleness_days"]
    if stale is not None and stale > MAX_NAV_STALENESS_DAYS:
        gate_failures.append(
            f"latest NAV is {stale} days stale (> {MAX_NAV_STALENESS_DAYS})"
        )

    drift_notes: list[str] = []
    if args.before:
        before = _load(args.before)
        before_idx = _index(before.get("rows", []))
        for cur in after_rows:
            prev = before_idx.get(cur["scheme_code"])
            if not prev:
                continue
            for k in ("return_1y_pct", "return_3y_pct", "return_5y_pct"):
                a, b = cur.get(k), prev.get(k)
                if a is None or b is None:
                    continue
                d = abs(a - b)
                if d > DRIFT_RETURN_PP_WARN:
                    drift_notes.append(
                        f"{cur['scheme_code']} {k}: drift {d:.2f}pp "
                        f"({b:.2f} -> {a:.2f}) — investigate"
                    )

    report = {
        "phase": "mf_phase1_data_foundation",
        "evaluated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "health": health,
        "gate_failures": gate_failures,
        "drift_notes_advisory": drift_notes,
        "passed": not gate_failures,
    }
    Path(args.report).write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8",
    )
    print(f"Schemes: {n_present}/{n_total} present, "
          f"staleness={health['staleness_days']} days")
    if gate_failures:
        for g in gate_failures:
            print(f"  FAIL: {g}")
    if drift_notes:
        print(f"Drift notes (advisory): {len(drift_notes)}")
    print(f"Report: {args.report}")
    print("STATUS:", "PASS" if report["passed"] else "FAIL")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
