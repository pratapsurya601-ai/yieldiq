"""
profile_memory_anchors.py
─────────────────────────
In-process memory profile of the FastAPI backend across the 12 anchor
tickers. Used by both CI (.github/workflows/memory-profile-check.yml)
and operators.

Why in-process?
  Spinning up the real uvicorn server in CI is slow and noisy; using
  httpx.AsyncClient with ASGITransport mounts the app directly in the
  same Python process so we can measure RSS deltas attributable to the
  app itself (not the runtime).

Usage
─────
  # Profile and compare against scripts/memory_baseline.json
  python scripts/profile_memory_anchors.py

  # Profile and overwrite the baseline (operator only, after intentional
  # memory changes like worker count tuning or new model loads)
  python scripts/profile_memory_anchors.py --update-baseline

  # Emit JSON only (no comparison, used by tests/dev)
  python scripts/profile_memory_anchors.py --json-only

Exit codes
──────────
  0  peak RSS within tolerance × baseline
  1  peak RSS > tolerance × baseline (regression)
  2  baseline missing and --update-baseline not passed
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Any

import psutil

_THIS = Path(__file__).resolve()
_ROOT = _THIS.parent.parent
_BASELINE = _THIS.parent / "memory_baseline.json"

# 12 anchor tickers — broad sector spread, matches docs/design/memory-baseline-investigation.md.
# Keep alphabetic for stable JSON diffs.
ANCHOR_TICKERS: list[str] = [
    "ASIANPAINT.NS",  # paints (consumer)
    "BAJFINANCE.NS",  # NBFC
    "EMBASSY.NS",     # REIT
    "HDFCBANK.NS",    # bank
    "HINDUNILVR.NS",  # FMCG
    "INFY.NS",        # IT
    "LT.NS",          # capital goods
    "MARUTI.NS",      # auto
    "ONGC.NS",        # PSU energy
    "RELIANCE.NS",    # conglomerate
    "SUNPHARMA.NS",   # pharma
    "TCS.NS",         # IT
]


def _rss_mb() -> float:
    return psutil.Process().memory_info().rss / (1024 * 1024)


async def _profile(app: Any) -> dict[str, Any]:
    """Hit each anchor's /api/v1/analysis endpoint sequentially and
    record RSS delta. Total peak is max RSS observed."""
    from httpx import ASGITransport, AsyncClient

    baseline_rss = _rss_mb()
    peak_rss = baseline_rss
    deltas: dict[str, float] = {}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for ticker in ANCHOR_TICKERS:
            before = _rss_mb()
            try:
                # 30s timeout per anchor — generous for cold cache miss.
                resp = await client.get(f"/api/v1/analysis/{ticker}", timeout=30.0)
                _ = resp.status_code  # we don't gate on status, just memory
            except Exception as exc:  # noqa: BLE001
                # Network / data errors do not fail the memory profile.
                # We still recorded "before" — leave delta at 0.
                print(f"  [warn] {ticker}: {type(exc).__name__}: {exc}", file=sys.stderr)
            after = _rss_mb()
            deltas[ticker] = round(after - before, 2)
            peak_rss = max(peak_rss, after)

    return {
        "baseline_rss_mb": round(baseline_rss, 2),
        "peak_rss_mb": round(peak_rss, 2),
        "anchor_rss_deltas_mb": deltas,
    }


def _load_app() -> Any:
    # Lazy import — keeps the script importable for tests without a full
    # FastAPI bootstrap.
    sys.path.insert(0, str(_ROOT))
    from backend.main import app  # noqa: PLC0415
    return app


def _compare(measured: dict[str, Any], baseline: dict[str, Any]) -> tuple[bool, str]:
    tolerance = float(baseline.get("tolerance", 1.20))
    base_peak = float(baseline["peak_rss_mb"])
    measured_peak = float(measured["peak_rss_mb"])
    ratio = measured_peak / base_peak if base_peak else 0.0
    threshold = base_peak * tolerance
    ok = measured_peak <= threshold
    msg = (
        f"peak_rss_mb={measured_peak:.1f} baseline={base_peak:.1f} "
        f"tolerance={tolerance:.2f}× threshold={threshold:.1f} ratio={ratio:.3f}"
    )
    return ok, msg


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile YieldIQ anchor memory usage.")
    parser.add_argument("--update-baseline", action="store_true",
                        help="Overwrite memory_baseline.json with current measurement.")
    parser.add_argument("--json-only", action="store_true",
                        help="Print JSON measurement and exit; skip baseline compare.")
    parser.add_argument("--output", type=str, default=None,
                        help="Write JSON measurement to this path (in addition to stdout).")
    args = parser.parse_args()

    app = _load_app()
    measured = asyncio.run(_profile(app))
    measured_json = json.dumps(measured, indent=2, sort_keys=True)
    print(measured_json)

    if args.output:
        Path(args.output).write_text(measured_json, encoding="utf-8")

    if args.json_only:
        return 0

    if args.update_baseline:
        # Preserve version field if it exists; otherwise leave blank for
        # operator to fill in PR description.
        prior_version = ""
        if _BASELINE.exists():
            try:
                prior = json.loads(_BASELINE.read_text(encoding="utf-8"))
                prior_version = prior.get("version", "")
            except json.JSONDecodeError:
                pass
        baseline_payload = {
            "version": prior_version,
            "captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "peak_rss_mb": measured["peak_rss_mb"],
            "anchor_rss_deltas_mb": measured["anchor_rss_deltas_mb"],
            "tolerance": 1.20,
        }
        _BASELINE.write_text(json.dumps(baseline_payload, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        print(f"\nUpdated baseline: {_BASELINE}", file=sys.stderr)
        return 0

    if not _BASELINE.exists():
        print(f"ERROR: baseline missing at {_BASELINE}. Run with --update-baseline.",
              file=sys.stderr)
        return 2

    baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))
    ok, msg = _compare(measured, baseline)
    status = "PASS" if ok else "FAIL"
    print(f"\n[{status}] {msg}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
