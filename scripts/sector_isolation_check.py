"""Sector-isolation merge gate — operates ONE layer ABOVE canary-diff.

Why this exists
---------------
Per-ticker canary (``canary_diff.py``) catches drift on individual stocks.
It does NOT catch **cross-sector leakage**, where a change meant for one
sector silently cascades across the whole universe.

PR #69 is the canary in the coal mine: a regulated-utility WACC change
(intended scope: utilities) moved SHREECEM -71 percent, AMBUJACEM -35
percent, BHARTIARTL score +16. None were in scope. Per-ticker canary
reported "drift — investigate" on each, but could not tell a reviewer
"Cement was not declared in sector-scope yet 3/3 Cement stocks shifted."

This script:
  1. Loads ``sector_snapshot.json`` — a committed baseline of per-sector
     median FV / score / MoS on the canary-50 universe.
  2. Fetches the current canary-50 via the existing ``canary_diff``
     harness (no duplication of HTTP code).
  3. Aggregates the current numbers by sector and diffs against the
     baseline.
  4. Reads a ``sector-scope:`` declaration from the PR body (or ``--scope``
     CLI arg).
  5. FAILS (exit 1) if any sector shifted more than the thresholds AND
     that sector is NOT in ``sector-scope``.
     Passes (exit 0) if every unexpected shift is within tolerance, or
     every shifted sector was explicitly declared.

Sector taxonomy
---------------
We use the ``sector`` field on ``scripts/canary_stocks_50.json`` entries
(human-readable labels: "Cement", "Banks", "Regulated Utility", ...).

Rationale — the analysis service internally calls
``models.industry_wacc.detect_sector`` which returns snake_case keys like
``regulated_utility``. Those keys drive WACC selection at scoring time,
so they are technically "what the service uses." However:

  - PR authors write ``sector-scope: Cement, Banks`` in English.
  - The canary-50 JSON already has a curated, stable ``sector`` field
    that is committed to the repo and reviewed by a human.
  - Mapping detect_sector() keys to pretty labels adds a brittle second
    source of truth.

So we treat the canary file's ``sector`` field as canonical for this
harness. If a future PR changes scoring in a way that shifts a
``detect_sector`` bucket without shifting the canary taxonomy, that
shift still manifests as per-ticker drift inside the relevant canary
sector bucket — the gate still catches it.

Thresholds
----------
Tuned to be LOOSER than per-ticker canary (which flags 15 percent FV
drift) because sector medians are more stable than individual tickers:

    median_fv    : 5 percent  (a 5 percent shift in a sector's median FV
                               across 3-7 stocks is real, not noise)
    median_score : 3 points   (yieldiq_score is 0-100 integer; 3pt median
                               shift = systemic)
    median_mos_pct : 5 pp     (advisory; informational column)

If a sector has fewer than MIN_TICKERS tickers with valid data, it is
reported as "insufficient_data" and excluded from gating — we never
fail a PR because one illiquid stock dropped out of the feed.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

# Ensure UTF-8 on Windows CI captures
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# Reuse the canary_diff fetch harness. This import is load-bearing: we
# MUST NOT duplicate the HTTP layer — the existing harness already
# handles requests/urllib fallback, auth headers, field extraction,
# verdict-aware skipping, and endpoint shape normalisation.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import canary_diff as cd  # noqa: E402

DEFAULT_SNAPSHOT = REPO_ROOT / "scripts" / "sector_snapshot.json"
DEFAULT_STOCKS = cd.DEFAULT_STOCKS

# Gating thresholds (see module docstring for derivation).
FV_DRIFT_PCT = 0.05       # 5 percent median-FV drift
SCORE_DRIFT_PT = 3.0      # 3 median-score points
MOS_DRIFT_PP = 5.0        # 5 percentage points on median MoS (advisory only)
MIN_TICKERS = 2           # below this, a sector is "insufficient_data"


def _median_or_none(xs: list[float]) -> float | None:
    xs = [x for x in xs if isinstance(x, (int, float)) and x is not None]
    if not xs:
        return None
    return float(statistics.median(xs))


def aggregate_by_sector(
    stocks: list[dict], state: dict[str, dict]
) -> dict[str, dict[str, Any]]:
    """Group canary state into per-sector aggregate medians.

    ``stocks`` is the canary_stocks_50.json list (carries the sector
    label); ``state`` is cd.collect_state output keyed by symbol.

    Prefers authed fields (canary-diff's "truth") when present, falls
    back to public. This keeps the gate runnable without CANARY_AUTH_TOKEN
    (public payload carries fair_value, mos, cmp, score) while still
    benefiting from the authed snapshot when it is available.

    Tickers with verdict=unavailable/avoid/under_review are skipped for
    that sector's medians — they carry sentinel zeros.
    """
    by_sector: dict[str, list[dict]] = {}
    for spec in stocks:
        sector = spec.get("sector") or "Unclassified"
        by_sector.setdefault(sector, []).append(spec)

    out: dict[str, dict[str, Any]] = {}
    for sector, specs in by_sector.items():
        tickers = [s["symbol"] for s in specs]
        fvs: list[float] = []
        scores: list[float] = []
        mos: list[float] = []
        iv_px: list[float] = []
        used: list[str] = []
        for spec in specs:
            sym = spec["symbol"]
            st = state.get(sym, {})
            au = st.get("authed") or {}
            pub = st.get("public") or {}
            # Prefer authed where present (canary "truth" layer); fall back
            # to public for public-only runs (no token available).
            truth = au if au else pub
            if not truth:
                continue
            if cd._has_no_dcf(truth):
                continue
            fv = cd._scalarize(truth.get("fair_value"))
            cmp_ = truth.get("cmp")
            mos_v = truth.get("margin_of_safety")
            # Score lives in the public summary payload under `score`;
            # extract_fields strips it, so we stash it in public via
            # _augment_scores. If absent, skip.
            score_v = pub.get("score") if isinstance(pub, dict) else None
            if cd._is_num(fv):
                fvs.append(float(fv))
            if cd._is_num(score_v):
                scores.append(float(score_v))
            if cd._is_num(mos_v):
                mos.append(float(mos_v))
            if cd._is_num(fv) and cd._is_num(cmp_) and cmp_ > 0:
                iv_px.append(float(fv) / float(cmp_))
            used.append(sym)
        out[sector] = {
            "tickers": tickers,
            "tickers_with_data": used,
            "median_fv": _median_or_none(fvs),
            "median_score": _median_or_none(scores),
            "median_mos_pct": _median_or_none(mos),
            "median_iv_px_ratio": _median_or_none(iv_px),
            "n_with_data": len(used),
        }
    return out


# ---------------------------------------------------------------------------
# Score-aware public fetch. canary_diff.extract_fields drops `score`; we
# need it for sector aggregation, so we re-fetch the raw payload and stash
# score into state[sym]["public"]["score"]. Single extra cost-free read.
# ---------------------------------------------------------------------------


def _augment_scores(stocks: list[dict], state: dict[str, dict]) -> None:
    """Ensure every state[sym]['public'] carries a 'score' key.

    ``canary_diff.extract_fields`` deliberately omits score (it's not one
    of the SHARED_FIELDS gated by canary). Rather than re-fetch, we
    re-run the public fetch once per ticker and patch. For a 50-stock
    canary this is ~50 extra GETs, still well under the 3-minute budget.
    """
    for spec in stocks:
        sym = spec["symbol"]
        st = state.get(sym)
        if not st:
            continue
        pub = st.get("public")
        if not isinstance(pub, dict):
            continue
        if "score" in pub:
            continue  # someone already patched
        raw, _err = cd.fetch_public(sym)
        if isinstance(raw, dict):
            pub["score"] = raw.get("score") or (raw.get("quality") or {}).get(
                "yieldiq_score"
            )


# ---------------------------------------------------------------------------
# Scope declaration parsing
# ---------------------------------------------------------------------------


def parse_scope(text: str | None) -> set[str] | None:
    """Extract ``sector-scope:`` from commit message / PR body.

    Returns None if no declaration is found (caller decides whether that
    is fatal). Returns ``{'*'}`` for an explicit global override.
    Otherwise returns a set of sector labels exactly as declared.
    Matching against the snapshot is case-insensitive.
    """
    if not text:
        return None
    for line in text.splitlines():
        s = line.strip()
        low = s.lower()
        if not low.startswith("sector-scope:"):
            continue
        payload = s.split(":", 1)[1].strip()
        if payload == "*":
            return {"*"}
        parts = [p.strip() for p in payload.split(",") if p.strip()]
        return set(parts)
    return None


def _norm(s: str) -> str:
    return s.strip().lower()


def scope_covers(scope: set[str], sector: str) -> bool:
    if not scope:
        return False
    if "*" in scope:
        return True
    return _norm(sector) in {_norm(x) for x in scope}


# ---------------------------------------------------------------------------
# Diff engine
# ---------------------------------------------------------------------------


def diff_sectors(
    baseline: dict[str, dict[str, Any]], current: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Produce a per-sector delta record.

    Status values:
      - ``ok``              : within all thresholds
      - ``shifted``         : at least one metric exceeded threshold
      - ``insufficient_data``: fewer than MIN_TICKERS with valid data
      - ``new_sector``      : present in current but not baseline (informational)
      - ``missing_sector``  : present in baseline but not current (informational)
    """
    records: list[dict[str, Any]] = []
    sectors = sorted(set(baseline) | set(current))
    for sector in sectors:
        b = baseline.get(sector)
        c = current.get(sector)
        rec: dict[str, Any] = {"sector": sector}
        if b is None:
            rec["status"] = "new_sector"
            rec["current"] = c
            records.append(rec)
            continue
        if c is None:
            rec["status"] = "missing_sector"
            rec["baseline"] = b
            records.append(rec)
            continue
        rec["baseline_fv"] = b.get("median_fv")
        rec["current_fv"] = c.get("median_fv")
        rec["baseline_score"] = b.get("median_score")
        rec["current_score"] = c.get("median_score")
        rec["baseline_mos"] = b.get("median_mos_pct")
        rec["current_mos"] = c.get("median_mos_pct")
        rec["n_current"] = c.get("n_with_data", 0)
        rec["n_baseline"] = b.get("n_with_data", 0)

        if rec["n_current"] < MIN_TICKERS:
            rec["status"] = "insufficient_data"
            records.append(rec)
            continue

        reasons: list[str] = []
        fv_drift_pct: float | None = None
        if cd._is_num(b.get("median_fv")) and cd._is_num(c.get("median_fv")) and b["median_fv"] != 0:
            fv_drift_pct = (c["median_fv"] - b["median_fv"]) / abs(b["median_fv"])
            if abs(fv_drift_pct) > FV_DRIFT_PCT:
                reasons.append(
                    f"median_fv {fv_drift_pct:+.1%} ({b['median_fv']:.2f} -> {c['median_fv']:.2f})"
                )
        score_delta: float | None = None
        if cd._is_num(b.get("median_score")) and cd._is_num(c.get("median_score")):
            score_delta = c["median_score"] - b["median_score"]
            if abs(score_delta) > SCORE_DRIFT_PT:
                reasons.append(
                    f"median_score {score_delta:+.1f}pt ({b['median_score']:.1f} -> {c['median_score']:.1f})"
                )
        mos_delta: float | None = None
        if cd._is_num(b.get("median_mos_pct")) and cd._is_num(c.get("median_mos_pct")):
            mos_delta = c["median_mos_pct"] - b["median_mos_pct"]
            # advisory only — NOT a gating condition
        rec["fv_drift_pct"] = fv_drift_pct
        rec["score_delta"] = score_delta
        rec["mos_delta_pp"] = mos_delta
        rec["status"] = "shifted" if reasons else "ok"
        rec["reasons"] = reasons
        records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _fmt(x: Any, spec: str = ".2f") -> str:
    if x is None:
        return "   -   "
    try:
        return format(x, spec)
    except Exception:
        return str(x)


def render_table(records: list[dict[str, Any]], scope: set[str] | None) -> str:
    header = (
        f"{'sector':<24}  {'status':<18}  {'in_scope':<9}  "
        f"{'fv%':>8}  {'score':>7}  {'mos_pp':>8}  n"
    )
    sep = "-" * len(header)
    lines = [header, sep]
    for r in records:
        sector = r["sector"]
        status = r.get("status", "?")
        in_scope = "yes" if scope and scope_covers(scope, sector) else "no"
        fvp = r.get("fv_drift_pct")
        fv_s = f"{fvp:+.1%}" if isinstance(fvp, float) else "   -   "
        sd = r.get("score_delta")
        sd_s = f"{sd:+.1f}" if isinstance(sd, float) else "  -   "
        mp = r.get("mos_delta_pp")
        mp_s = f"{mp:+.1f}" if isinstance(mp, float) else "  -   "
        n = r.get("n_current", r.get("n_baseline", "-"))
        lines.append(
            f"{sector:<24}  {status:<18}  {in_scope:<9}  "
            f"{fv_s:>8}  {sd_s:>7}  {mp_s:>8}  {n}"
        )
    return "\n".join(lines)


def summarise(
    records: list[dict[str, Any]], scope: set[str] | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (unexpected_shifts, declared_shifts, advisory)."""
    unexpected: list[dict[str, Any]] = []
    declared: list[dict[str, Any]] = []
    advisory: list[dict[str, Any]] = []
    for r in records:
        if r.get("status") == "shifted":
            if scope and scope_covers(scope, r["sector"]):
                declared.append(r)
            else:
                unexpected.append(r)
        elif r.get("status") in ("new_sector", "missing_sector", "insufficient_data"):
            advisory.append(r)
    return unexpected, declared, advisory


# ---------------------------------------------------------------------------
# Scope discovery helpers
# ---------------------------------------------------------------------------


def _fetch_pr_body_via_gh(pr_number: str) -> str | None:
    try:
        out = subprocess.check_output(
            ["gh", "pr", "view", pr_number, "--json", "body", "-q", ".body"],
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return out.decode("utf-8", errors="replace")
    except Exception:
        return None


def discover_scope(args: argparse.Namespace) -> tuple[set[str] | None, str]:
    """Resolve sector-scope from (in priority order): explicit --scope,
    --pr-body-file, GITHUB_EVENT_PATH (GH Actions PR body), gh CLI with
    --pr-number, or the latest commit message.

    Returns (scope_set_or_None, source_description).
    """
    if args.scope is not None:
        return parse_scope(f"sector-scope: {args.scope}"), "cli --scope"
    if args.pr_body_file:
        try:
            text = Path(args.pr_body_file).read_text(encoding="utf-8")
            return parse_scope(text), f"file {args.pr_body_file}"
        except Exception as e:  # noqa: BLE001
            print(f"warning: could not read --pr-body-file: {e}", file=sys.stderr)
    ev_path = os.environ.get("GITHUB_EVENT_PATH")
    if ev_path and Path(ev_path).exists():
        try:
            ev = json.loads(Path(ev_path).read_text(encoding="utf-8"))
            body = (ev.get("pull_request") or {}).get("body") or ""
            if body:
                return parse_scope(body), "GITHUB_EVENT_PATH pull_request.body"
        except Exception:
            pass
    if args.pr_number:
        body = _fetch_pr_body_via_gh(args.pr_number)
        if body:
            return parse_scope(body), f"gh pr view {args.pr_number}"
    # last resort — latest commit message
    try:
        msg = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode("utf-8", errors="replace")
        return parse_scope(msg), "git log HEAD"
    except Exception:
        return None, "none"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_state_from_snapshot(path: Path) -> dict[str, dict]:
    """Load a canary_diff snapshot file and return its state dict.

    Enables re-using a fresh canary run's snapshot so we don't double-fetch
    the whole universe on the same CI run. The sector-isolation workflow
    does NOT require this — it's for local debugging.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw.get("state") if isinstance(raw, dict) and "state" in raw else raw


def run(
    baseline: dict[str, dict[str, Any]],
    stocks: list[dict],
    state: dict[str, dict],
    scope: set[str] | None,
    verbose: bool = False,
) -> tuple[int, dict[str, Any]]:
    current = aggregate_by_sector(stocks, state)
    records = diff_sectors(baseline, current)
    unexpected, declared, advisory = summarise(records, scope)
    table = render_table(records, scope)
    report = {
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "commit_sha": cd._git_sha(),
        "scope_declared": sorted(scope) if scope else None,
        "unexpected_shifts": unexpected,
        "declared_shifts": declared,
        "advisory": advisory,
        "sectors": current,
        "table": table,
    }
    exit_code = 1 if unexpected else 0
    return exit_code, report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="YieldIQ sector-isolation merge gate — catches cross-sector leakage"
    )
    p.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT),
                   help="path to sector_snapshot.json baseline")
    p.add_argument("--stocks", default=str(DEFAULT_STOCKS),
                   help="path to canary_stocks_50.json")
    p.add_argument("--state-from", default=None,
                   help="reuse a canary_diff --snapshot file (skips API fetch)")
    p.add_argument("--scope", default=None,
                   help="explicit sector-scope CSV (e.g. 'Cement,Banks' or '*')")
    p.add_argument("--pr-body-file", default=None,
                   help="file containing the PR body to parse for sector-scope:")
    p.add_argument("--pr-number", default=None,
                   help="GH PR number; body is fetched via gh CLI")
    p.add_argument("--report-json", default="sector_isolation_report.json")
    p.add_argument("--report-md", default="sector_isolation_report.md")
    p.add_argument("--require-scope", action="store_true",
                   help="fail if no sector-scope declaration is found (recommended in CI)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    snapshot_path = Path(args.snapshot)
    if not snapshot_path.exists():
        print(f"ERROR: sector_snapshot.json not found at {snapshot_path}", file=sys.stderr)
        print("Run scripts/update_sector_snapshot.py --reason 'initial baseline' to create it.",
              file=sys.stderr)
        return 2
    baseline_raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    baseline = baseline_raw.get("sectors") or {}

    stocks = cd.load_stocks(Path(args.stocks))

    scope, scope_src = discover_scope(args)
    if args.verbose:
        print(f"scope source: {scope_src}", flush=True)
        print(f"scope: {sorted(scope) if scope else '(none declared)'}", flush=True)

    if scope is None and args.require_scope:
        print(
            "ERROR: no `sector-scope:` declaration found.\n"
            "Every PR touching scoring code must declare:\n"
            "  sector-scope: Cement, Banks        (sectors intentionally touched)\n"
            "  sector-scope: *                    (intentionally-global change)\n"
            "in the PR body. See docs/SECTOR_ISOLATION.md.",
            file=sys.stderr,
        )
        return 2

    if args.state_from:
        state = _load_state_from_snapshot(Path(args.state_from))
        # Snapshots written by canary_diff don't carry 'score' in public
        # unless we asked for it; augment now.
        _augment_scores(stocks, state)
    else:
        print(
            f"Sector-isolation: fetching {len(stocks)} stocks from {cd.API_BASE}",
            flush=True,
        )
        state = cd.collect_state(
            stocks, api_base=cd.API_BASE, token=cd.AUTH_TOKEN, verbose=args.verbose
        )
        _augment_scores(stocks, state)

    exit_code, report = run(baseline, stocks, state, scope, verbose=args.verbose)

    Path(args.report_json).write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    md = _render_markdown(report)
    Path(args.report_md).write_text(md, encoding="utf-8")

    print()
    print(report["table"])
    print()
    if report["unexpected_shifts"]:
        print(f"FAIL — {len(report['unexpected_shifts'])} unexpected sector shift(s):")
        for r in report["unexpected_shifts"]:
            print(f"  - {r['sector']}: {'; '.join(r.get('reasons') or [])}")
        print()
        print("Either:")
        print("  1. Declare these sectors in the PR body: `sector-scope: "
              + ", ".join(r["sector"] for r in report["unexpected_shifts"]) + "`")
        print("  2. Investigate per-ticker to find the leak "
              "(re-run canary_diff.py --verbose and diff against the snapshot).")
        print("  3. If intentional, rebaseline after human review: "
              "python scripts/update_sector_snapshot.py --reason '<why>'")
    else:
        print("PASS — no unexpected sector shifts.")
    if report["declared_shifts"]:
        print(f"\n{len(report['declared_shifts'])} declared shift(s) accepted:")
        for r in report["declared_shifts"]:
            print(f"  - {r['sector']}: {'; '.join(r.get('reasons') or [])}")

    return exit_code


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Sector Isolation Report",
        "",
        f"Commit: `{report['commit_sha']}`  ",
        f"Timestamp: {report['timestamp']}  ",
        f"Scope declared: `{report['scope_declared']}`",
        "",
        "```",
        report["table"],
        "```",
        "",
    ]
    if report["unexpected_shifts"]:
        lines.append("## Unexpected shifts (gate FAIL)")
        for r in report["unexpected_shifts"]:
            lines.append(f"- **{r['sector']}** — " + "; ".join(r.get("reasons") or []))
        lines.append("")
    if report["declared_shifts"]:
        lines.append("## Declared shifts (accepted via sector-scope)")
        for r in report["declared_shifts"]:
            lines.append(f"- **{r['sector']}** — " + "; ".join(r.get("reasons") or []))
        lines.append("")
    if report["advisory"]:
        lines.append("## Advisory")
        for r in report["advisory"]:
            lines.append(f"- **{r['sector']}**: {r.get('status')}")
        lines.append("")
    lines.append("---")
    lines.append(
        "STATUS: " + ("FAIL" if report["unexpected_shifts"] else "PASS")
    )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
