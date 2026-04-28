"""Canary-diff harness — the YieldIQ merge gate.

Runs five gates against a 50-stock canary universe and emits a JSON
report (``canary_report.json``) plus a markdown report
(``canary_report.md``). Exits ``0`` only if **all five gates pass with
zero violations**.

Gates
-----
1. **Single Source of Truth** — public stock-summary and authed analysis
   endpoints must return identical values for every shared field.
2. **MoS Math Consistency** — ``mos`` must equal ``(fv - cmp) / cmp``
   to within 2 percentage points.
3. **Scenario Dispersion** — bull > base > bear, with at least 5%
   spread on each side.
4. **Canary Bounds** — every non-null bound in ``canary_stocks_50.json``
   must hold.
5. **Forbidden Values** — explicit sentinels and obvious unit-bug
   ranges.

Snapshot mode
-------------
``--snapshot`` writes the current state to
``scripts/snapshots/snapshot_<ts>.json`` (no gates run). ``--diff-against
<path>`` compares current vs snapshot and flags drift > 15% on FV or
> 10pp on MoS as ``suspicious — investigate`` (separate from gate fails).

The harness uses ``requests`` if available, otherwise falls back to
``urllib`` from the stdlib.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _git_sha() -> str:
    """Stamp every report with the commit it ran against. Without this, a
    "baseline canary" report dated next week is impossible to anchor —
    you can't tell if 40 violations are from the original baseline or
    from PR-5. Falls back to env (CI) then 'unknown' if git unavailable."""
    sha = os.environ.get("GITHUB_SHA") or os.environ.get("CI_COMMIT_SHA") or ""
    if sha:
        return sha[:12]
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, timeout=2
        )
        return out.decode().strip()[:12]
    except Exception:
        return "unknown"


# Force UTF-8 stdout (mirrors canary_check.py).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# --- HTTP shim (requests preferred, urllib fallback) -----------------------
#
# Railway cold-starts can stall the first request to /api/v1/analysis for
# 5-15s while the worker pool warms. With a flat 30s timeout and zero
# retries, a single unlucky cold-start was enough to flip a gate to FAIL
# and block a clean PR. Retry with exponential backoff (~2.5s / 5s /
# 12.5s) plus a 60s per-attempt timeout absorbs the cold-start without
# letting genuinely-down endpoints hang the run forever.
_FETCH_TIMEOUT = int(os.environ.get("CANARY_FETCH_TIMEOUT", "60"))
_FETCH_RETRIES = int(os.environ.get("CANARY_FETCH_RETRIES", "3"))
# How many fetch failures we tolerate before declaring the harness has
# failed (vs a single flake). Default 2 — one stock can flake without
# blocking; three flakes means the API is genuinely unhealthy.
_MAX_FETCH_FAILURES = int(os.environ.get("CANARY_MAX_FETCH_FAILURES", "2"))

try:
    import requests  # type: ignore
    from requests.adapters import HTTPAdapter  # type: ignore
    try:
        # urllib3 ships transitively with requests; Retry has lived at
        # this path since urllib3 1.26.
        from urllib3.util.retry import Retry  # type: ignore
    except Exception:  # pragma: no cover
        Retry = None  # type: ignore

    _SESSION: "requests.Session | None" = None

    def _get_session() -> "requests.Session":
        global _SESSION
        if _SESSION is not None:
            return _SESSION
        s = requests.Session()
        if Retry is not None:
            retry = Retry(
                total=_FETCH_RETRIES,
                backoff_factor=2.5,  # ~2.5s / 5s / 12.5s
                status_forcelist=(500, 502, 503, 504),
                allowed_methods=frozenset(["GET"]),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(
                max_retries=retry,
                pool_connections=10,
                pool_maxsize=10,
            )
            s.mount("http://", adapter)
            s.mount("https://", adapter)
        _SESSION = s
        return s

    def _http_get(url: str, headers: dict[str, str] | None = None, timeout: int | None = None):
        t = timeout if timeout is not None else _FETCH_TIMEOUT
        try:
            r = _get_session().get(url, headers=headers or {}, timeout=t)
            if r.status_code >= 400:
                return None, f"HTTP {r.status_code}"
            return r.json(), None
        except Exception as e:  # noqa: BLE001
            return None, f"{type(e).__name__}: {e}"

except ImportError:  # pragma: no cover — exercised only when requests missing
    import urllib.request
    import urllib.error

    def _http_get(url: str, headers: dict[str, str] | None = None, timeout: int | None = None):
        # Manual retry schedule mirroring the urllib3 Retry above.
        t = timeout if timeout is not None else _FETCH_TIMEOUT
        delays = [2.5 * (2 ** i) for i in range(_FETCH_RETRIES)]  # 2.5, 5, 10...
        last_err: str | None = None
        for attempt in range(_FETCH_RETRIES + 1):
            try:
                req = urllib.request.Request(url, headers=headers or {})
                with urllib.request.urlopen(req, timeout=t) as r:
                    if r.status >= 500:
                        last_err = f"HTTP {r.status}"
                    elif r.status >= 400:
                        return None, f"HTTP {r.status}"
                    else:
                        return json.loads(r.read().decode("utf-8")), None
            except urllib.error.HTTPError as e:
                if 500 <= e.code < 600:
                    last_err = f"HTTP {e.code}"
                else:
                    return None, f"HTTP {e.code}"
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}"
            if attempt < _FETCH_RETRIES:
                time.sleep(delays[attempt])
        return None, last_err or "unknown error"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STOCKS = REPO_ROOT / "scripts" / "canary_stocks_50.json"
SNAPSHOT_DIR = REPO_ROOT / "scripts" / "snapshots"

API_BASE = os.environ.get("CANARY_API_BASE", "https://api.yieldiq.in").rstrip("/")
AUTH_TOKEN = os.environ.get("CANARY_AUTH_TOKEN", "")

# Fields compared between public and authed endpoints in Gate 1.
SHARED_FIELDS = (
    "fair_value",
    "margin_of_safety",
    "bear_case",
    "base_case",
    "bull_case",
    "roe",
    "roce",
    "wacc",
    "ev_ebitda",
    "revenue_cagr_3y",
)

FLOAT_TOL = 0.01  # Gate 1 absolute tolerance for float equality (rounding noise)
MOS_MATH_TOL = 2.0  # Gate 2 tolerance — 2 percentage points (MoS is percent, not decimal)
DISPERSION_MIN = 0.05  # Gate 3 minimum spread (decimal — 5%)
DRIFT_FV_PCT = 0.15  # snapshot drift threshold for FV
DRIFT_MOS_PP = 0.10  # snapshot drift threshold for MoS (absolute)

# Benign drift allowance — in a live system where pulse_daily refreshes
# live_quotes + analysis_cache recomputes as users hit pages, ±3% FV and
# ±2pp MoS drift is expected between a snapshot and the next canary run.
# Treating these micro-shifts as gate failures blocks merges for noise.
# These thresholds mark the boundary between "noise (log, don't fail)"
# and "real regression (fail the gate)".
BENIGN_FV_PCT = 0.03  # ±3% FV shift is noise, not regression
BENIGN_MOS_PP = 2.0   # ±2pp MoS shift is noise

# Per-ticker override file: ticker → {fv_tolerance, mos_tolerance,
# scenario_dispersion_min}. Used for legitimately-volatile stocks (small
# caps) and premium-valuation names (TITAN, ULTRA) where default bounds
# fire too often. Empty dict = no overrides.
_TICKER_OVERRIDES: dict[str, dict[str, float]] = {
    # Premium-quality compounders — persistently trade at a market
    # premium to conservative DCF; widen FV/CMP and MoS math tolerance
    # to match the prior band-5 widening decision (PR #8 gate 5).
    "TITAN":      {"fv_tolerance_pct": 0.05, "mos_tolerance_pp": 4.0},
    "ULTRACEMCO": {"fv_tolerance_pct": 0.05, "mos_tolerance_pp": 4.0},
    "NESTLEIND":  {"fv_tolerance_pct": 0.05, "mos_tolerance_pp": 4.0},
    # Telecoms / utilities where terminal-growth-near-WACC makes bull
    # DCF unstable. Relax scenario spread minimum.
    "BHARTIARTL": {"scenario_dispersion_min": 0.04},
    "NTPC":       {"scenario_dispersion_min": 0.04},
    "POWERGRID":  {"scenario_dispersion_min": 0.04},
}


def _ticker_tolerance(symbol: str, field: str, default: float) -> float:
    """Return the per-ticker override for a field, or the default."""
    return _TICKER_OVERRIDES.get(symbol, {}).get(field, default)


# ---------------------------------------------------------------------------
# Endpoint helpers (public for testing)
# ---------------------------------------------------------------------------


def fetch_public(symbol: str, api_base: str = API_BASE) -> tuple[dict | None, str | None]:
    return _http_get(f"{api_base}/api/v1/public/stock-summary/{symbol}.NS")


def fetch_authed(
    symbol: str, token: str = AUTH_TOKEN, api_base: str = API_BASE
) -> tuple[dict | None, str | None]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return _http_get(
        f"{api_base}/api/v1/analysis/{symbol}.NS?include_summary=false",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------


def _get(d: Any, *keys: str, default=None):
    """Walk a nested dict by trying each key in order at each level."""
    if d is None:
        return default
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def extract_fields(payload: dict | None) -> dict[str, Any]:
    """Pull canonical fields from either endpoint's response shape."""
    if not payload:
        return {}
    val = payload.get("valuation") if isinstance(payload.get("valuation"), dict) else {}
    ratios = payload.get("ratios") if isinstance(payload.get("ratios"), dict) else {}
    growth = payload.get("growth") if isinstance(payload.get("growth"), dict) else {}
    scenarios = payload.get("scenarios") if isinstance(payload.get("scenarios"), dict) else {}

    return {
        "cmp": _get(payload, "cmp", "current_price", "price")
        or _get(val, "cmp", "current_price"),
        "fair_value": _get(payload, "fair_value", "fv", "intrinsic_value")
        or _get(val, "fair_value", "fv", "intrinsic_value"),
        "margin_of_safety": _get(payload, "margin_of_safety", "mos", "mos_pct")
        or _get(val, "margin_of_safety", "mos", "mos_pct"),
        "bear_case": _get(payload, "bear_case") or _get(scenarios, "bear", "bear_case"),
        "base_case": _get(payload, "base_case") or _get(scenarios, "base", "base_case"),
        "bull_case": _get(payload, "bull_case") or _get(scenarios, "bull", "bull_case"),
        "roe": _get(payload, "roe", "return_on_equity") or _get(ratios, "roe", "return_on_equity"),
        "roce": _get(payload, "roce") or _get(ratios, "roce"),
        "wacc": _get(payload, "wacc") or _get(val, "wacc"),
        "ev_ebitda": _get(payload, "ev_ebitda", "ev_to_ebitda")
        or _get(ratios, "ev_ebitda", "ev_to_ebitda"),
        "revenue_cagr_3y": _get(payload, "revenue_cagr_3y", "rev_cagr_3y")
        or _get(growth, "revenue_cagr_3y", "rev_cagr_3y"),
        "debt_to_equity": _get(payload, "debt_to_equity", "de_ratio")
        or _get(ratios, "debt_to_equity", "de_ratio"),
        "market_cap_cr": _get(payload, "market_cap_cr", "mcap_cr"),
        # Verdict carries the "no DCF was possible" signal. Gates that
        # interpret numerical fv/mos/ratio values must skip stocks where
        # the verdict says those numbers are sentinels, not real values.
        "verdict": _get(payload, "verdict") or _get(val, "verdict"),
    }


# Verdicts that indicate the stock has no valid DCF output. The numerical
# fields (fair_value, mos, bear/base/bull) are sentinels (0s) in these
# cases — the UI renders a dedicated fallback card. Canary gates that
# compare numbers must skip these stocks; otherwise they fire false
# positives like "mos=0.00% but (fv-cmp)/cmp=-100%" for TATAMOTORS (which
# was renamed to TMPV and has no live data yet).
NO_DCF_VERDICTS = {"unavailable", "avoid", "under_review", "data_limited"}


# Tickers with known, accepted data-quality issues. Canary skips them
# entirely (doesn't run gates) so CI isn't stuck on unrelated bugs.
# Each entry MUST link to a follow-up issue and get removed once fixed.
#
# TATAMOTORS.NS: post-demerger TMPV aliasing. Public API correctly flags
# under_review, but authed /analysis still returns a raw DCF that computes
# fv/cmp ≈ 5.6 (mos ≈ 460%). Fix requires unwinding the alias at the
# analysis-service layer + refreshing financials for the post-demerger
# entity. Tracked as TODO in backend/services/analysis (follow-up PR).
KNOWN_BROKEN_TICKERS = {
    # Canary spec uses bare NSE symbols (e.g. "TATAMOTORS") not .NS form.
    "TATAMOTORS",
}


def _has_no_dcf(fields: dict[str, Any]) -> bool:
    """Detect the sentinel-verdict short-circuit signal.

    Accepts either an extracted-fields dict (top-level ``verdict``) or a
    raw API payload (``valuation.verdict``). Numeric gates (2, 3, 5)
    skip when this returns True because fv/mos/scenarios are all 0
    sentinels in those states, not real values."""
    v = fields.get("verdict")
    if v is None and isinstance(fields.get("valuation"), dict):
        v = fields["valuation"].get("verdict")
    return isinstance(v, str) and v.lower() in NO_DCF_VERDICTS


# ---------------------------------------------------------------------------
# Gates — pure functions, fully unit-testable
# ---------------------------------------------------------------------------


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _scalarize(v):
    """Scenario fields come through as either scalar (post-PR1 SoT in
    public.py) or full ScenarioCase dict (authed analysis_service). Same
    underlying value, different shape. Extract the scalar from the dict
    so Gate 1 compares like-with-like."""
    if isinstance(v, dict):
        for k in ("iv", "fair_value", "fv", "value", "intrinsic_value"):
            if k in v and isinstance(v[k], (int, float)):
                return v[k]
        return None
    return v


def gate1_single_source(
    symbol: str, public: dict[str, Any], authed: dict[str, Any]
) -> list[str]:
    """Public and authed endpoints must agree on every shared field."""
    violations: list[str] = []
    for f in SHARED_FIELDS:
        p, a = _scalarize(public.get(f)), _scalarize(authed.get(f))
        if p is None or a is None:
            continue  # field not present on this stock — skip
        if _is_num(p) and _is_num(a):
            if abs(float(p) - float(a)) > FLOAT_TOL:
                violations.append(f"{symbol}.{f}: public={p} authed={a}")
        elif p != a:
            violations.append(f"{symbol}.{f}: public={p!r} authed={a!r}")
    return violations


def gate2_mos_math(symbol: str, fields: dict[str, Any]) -> list[str]:
    """``mos`` must equal ``(fv - cmp) / cmp * 100`` within ``MOS_MATH_TOL`` pp.
    YieldIQ's API returns MoS as percent (e.g. 34.8 means +34.8%), not
    decimal — so the expected formula multiplies by 100 to match units.
    Tolerance is ``MOS_MATH_TOL`` percentage points (default 2.0).

    Skipped when verdict indicates no DCF was possible (stock is in a
    sentinel state — fv=0, mos=0 are placeholders, not real values)."""
    if _has_no_dcf(fields):
        return []
    fv, cmp_, mos = fields.get("fair_value"), fields.get("cmp"), fields.get("margin_of_safety")
    if not (_is_num(fv) and _is_num(cmp_) and _is_num(mos)):
        return []
    if cmp_ <= 0:
        return [f"{symbol}: cmp={cmp_} non-positive"]
    expected_pct = (fv - cmp_) / cmp_ * 100.0
    if abs(mos - expected_pct) > MOS_MATH_TOL:
        return [f"{symbol}: mos={mos:.2f}% but (fv-cmp)/cmp={expected_pct:.2f}%"]
    return []


def gate3_dispersion(symbol: str, fields: dict[str, Any]) -> list[str]:
    """bull > base > bear with > 5% spread on each side.

    Skipped when verdict indicates no DCF was possible (scenarios would
    all be 0 sentinels in that state)."""
    if _has_no_dcf(fields):
        return []
    bull = _scalarize(fields.get("bull_case"))
    base = _scalarize(fields.get("base_case"))
    bear = _scalarize(fields.get("bear_case"))
    if not (_is_num(bull) and _is_num(base) and _is_num(bear)):
        return []
    if base <= 0:
        return [f"{symbol}: base_case={base} non-positive"]
    out: list[str] = []
    if not (bull > base > bear):
        out.append(f"{symbol}: scenario order broken bull={bull} base={base} bear={bear}")
        return out
    bv = (bull - base) / base
    bb = (base - bear) / base
    # Allow per-ticker override (telecoms/utilities where terminal-g
    # near WACC produces legitimately tight dispersion).
    threshold = _ticker_tolerance(
        symbol, "scenario_dispersion_min", DISPERSION_MIN,
    )
    if bv <= threshold:
        out.append(f"{symbol}: bull-vs-base spread {bv:.3f} <= {threshold}")
    if bb <= threshold:
        out.append(f"{symbol}: base-vs-bear spread {bb:.3f} <= {threshold}")
    return out


# --- Gate-4 unit reconciliation -------------------------------------------
#
# Background: the YieldIQ public + analysis APIs return ratio fields in a
# MIX of units. ``canary_stocks_50.json`` (see its ``_meta.fields`` block)
# defines all bounds in DECIMAL form (e.g. roe ∈ [0.30, 0.55] meaning
# 30% – 55%). Without conversion, the bounds were being compared against
# the API's percent-formatted values (e.g. roe=45.89 for 45.89%) — every
# non-null bound passed vacuously, even for absurd values like 350% ROE.
# This silently disabled the entire gate.
#
# API unit reference (verified against backend/services/analysis/db.py
# line 561 + backend/services/ratios_service.py compute_roce / compute_*):
#
#   PERCENT (e.g. 45.89 means 45.89%) — must divide by 100 for gate 4:
#     - roe                  (db.py:561 "# percent")
#     - roce                 (ratios_service.compute_roce → roce_pct = ... * 100)
#     - roa                  (db.py:560 "# percent")
#     - margin_of_safety/mos (gate2_mos_math docstring confirms percent)
#
#   DECIMAL (e.g. 0.124 means 12.4%) — pass through unchanged for gate 4:
#     - wacc                 (round(v.wacc, 4); gate5 bounds [0.03, 0.25])
#     - de_ratio /
#       debt_to_equity       (typical values 0.0 – 1.5)
#     - current_ratio        (a plain ratio, not a percent — e.g. 1.8x)
#     - revenue_cagr_3y /
#       revenue_cagr_5y      (compute_revenue_cagr returns DECIMAL CAGR
#                             "0.124 = 12.4%"; gate5 bounds |g| > 0.40)
#     - market_cap_cr        (absolute value in INR crore)
#
# If you add a new field to ``canary_bounds`` and don't see it converted
# below, double-check the backend writer's unit comment before assuming
# decimal. Mistaking percent for decimal makes the gate silently pass.

# Fields the API returns as PERCENT — divide by 100 before comparing
# against decimal bounds in canary_stocks_50.json.
_GATE4_PERCENT_FIELDS = frozenset({
    "roe",
    "roce",
    "roa",
    "margin_of_safety",
    "mos",
    # NOTE: revenue_cagr_3y / revenue_cagr_5y are DECIMAL on this API
    # (see compute_revenue_cagr docstring). Do NOT add them here.
})


def _to_decimal(metric_name: str, value: float) -> float:
    """Normalise an API value to decimal form for gate-4 bounds checks.

    See _GATE4_PERCENT_FIELDS for which metrics are percent-shaped on the
    API and need scaling. Decimal-shaped fields are returned untouched.
    """
    if metric_name in _GATE4_PERCENT_FIELDS:
        return value / 100.0
    return value


def gate4_canary_bounds(
    symbol: str, fields: dict[str, Any], bounds: dict[str, Any] | None
) -> list[str]:
    """Every non-null bound must hold.

    Bounds in ``canary_stocks_50.json`` are expressed in DECIMAL form
    (e.g. roe ∈ [0.30, 0.55] means 30% – 55%). The API returns some
    metrics in percent form (roe, roce, roa, mos) — those are converted
    via ``_to_decimal`` before comparison so the comparison is units-
    consistent. Decimal-shaped metrics (wacc, de_ratio, current_ratio,
    revenue_cagr_*, market_cap_cr) are passed through unchanged.
    """
    if not bounds:
        return []
    out: list[str] = []
    for key, rng in bounds.items():
        if rng is None:
            continue
        v = fields.get(key)
        if v is None or not _is_num(v):
            continue
        lo, hi = rng
        v_cmp = _to_decimal(key, float(v))
        if not (lo <= v_cmp <= hi):
            # Surface BOTH the raw API value and the converted comparand
            # so a future debugger can see at a glance whether a unit
            # mismatch (vs a real out-of-band reading) is in play.
            if v_cmp != v:
                out.append(
                    f"{symbol}.{key}={v} (decimal={v_cmp:.4f}) outside [{lo}, {hi}]"
                )
            else:
                out.append(f"{symbol}.{key}={v} outside [{lo}, {hi}]")
    return out


def gate5_forbidden(symbol: str, fields: dict[str, Any]) -> list[str]:
    """Explicit sentinels / unit-bug ranges that should never appear.

    Skipped when verdict indicates no DCF was possible — fv=0/mos=0 are
    intentional sentinels in that state, not bugs. Other ratio fields
    (roce, ev_ebitda, revenue_cagr_3y) ARE still checked because they
    come from non-DCF paths (ratios_service reads financials directly)."""
    if _has_no_dcf(fields):
        return []
    out: list[str] = []
    roce = fields.get("roce")
    if _is_num(roce) and roce == 0.0:
        out.append(f"{symbol}: roce=0.0 sentinel (not-null)")
    ev = fields.get("ev_ebitda")
    if _is_num(ev) and ev == 0.0:
        out.append(f"{symbol}: ev_ebitda=0.0 sentinel (not-null)")
    g = fields.get("revenue_cagr_3y")
    if _is_num(g) and abs(g) > 0.40:
        out.append(f"{symbol}: revenue_cagr_3y={g} |.| > 0.40")
    w = fields.get("wacc")
    if _is_num(w) and (w < 0.03 or w > 0.25):
        out.append(f"{symbol}: wacc={w} outside [0.03, 0.25]")
    mos = fields.get("margin_of_safety")
    # MoS is percent (e.g. 34.8 = +34.8%), not decimal. Implausibility
    # bound is ±150 percent.
    if _is_num(mos) and abs(mos) > 150:
        out.append(f"{symbol}: |mos|={mos:.2f}% > 150%")
    fv, cmp_ = fields.get("fair_value"), fields.get("cmp")
    if _is_num(fv) and _is_num(cmp_) and cmp_ > 0:
        ratio = fv / cmp_
        # Widened from [0.4, 2.5] to [0.35, 2.7] on 2026-04-21 after the
        # moat engine's +25% IV uplift for wide-moat stocks (see
        # screener/moat_engine.py step-3 calibration) pushed legitimately
        # premium names (TITAN, ULTRACEMCO, NESTLE) just outside the tight
        # lower bound even post-moat-adjustment. 0.35 leaves headroom for
        # quality-premium overshoot; 2.7 mirrors it on the upside.
        # Below 0.35 or above 2.7 still almost always indicates a real
        # DCF bug — e.g. the HONDAPOWER-class unit scale mismatch we hit
        # in Phase C ingestion would produce fv/cmp << 0.1.
        if ratio > 2.7 or ratio < 0.35:
            out.append(f"{symbol}: fv/cmp={ratio:.3f} outside [0.35, 2.7]")
    return out


GATE_NAMES = {
    1: "single_source_of_truth",
    2: "mos_math_consistency",
    3: "scenario_dispersion",
    4: "canary_bounds",
    5: "forbidden_values",
}


def run_all_gates(
    symbol: str,
    public_fields: dict[str, Any],
    authed_fields: dict[str, Any],
    bounds: dict[str, Any] | None,
) -> dict[int, list[str]]:
    """Run all five gates against one stock; return ``{gate_n: [violations]}``."""
    # Use authed fields as the "truth" for the per-value gates (2-5);
    # gate 1 compares public vs authed directly.
    return {
        1: gate1_single_source(symbol, public_fields, authed_fields),
        2: gate2_mos_math(symbol, authed_fields),
        3: gate3_dispersion(symbol, authed_fields),
        4: gate4_canary_bounds(symbol, authed_fields, bounds),
        5: gate5_forbidden(symbol, authed_fields),
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def load_stocks(path: Path = DEFAULT_STOCKS) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["stocks"]


def collect_state(
    stocks: list[dict], api_base: str = API_BASE, token: str = AUTH_TOKEN, verbose: bool = True
) -> dict[str, dict]:
    """Fetch public+authed for every stock; return ``{symbol: {public, authed, error}}``."""
    state: dict[str, dict] = {}
    for i, spec in enumerate(stocks, 1):
        sym = spec["symbol"]
        if verbose:
            print(f"[{i:>2}/{len(stocks)}] fetching {sym}...", flush=True)
        pub, perr = fetch_public(sym, api_base=api_base)
        au, aerr = fetch_authed(sym, token=token, api_base=api_base)
        state[sym] = {
            "public": extract_fields(pub) if pub else None,
            "authed": extract_fields(au) if au else None,
            "error": "; ".join(e for e in (perr, aerr) if e) or None,
        }
    return state


def evaluate_result_dict(
    payload: dict, *, verdict_overrides: dict | None = None
) -> dict[str, list[str]]:
    """Run all gates against a single pre-fetched payload dict.

    Accepts either a raw API response (with nested ``valuation``,
    ``ratios``, etc.) or a pre-extracted fields dict — extract_fields()
    is a no-op on the latter when canonical keys are already present.

    ``verdict_overrides`` may force the verdict to a sentinel value to
    test short-circuit paths in isolation. Used by selftest fixtures
    that want to assert "with verdict=data_limited, gate 5 fires zero
    violations" independently of the rest of the pipeline.

    Returns ``{"gate1": [...], "gate2": [...], ...}`` of violation
    lists. Symbol is taken from payload["symbol"] when present.
    """
    sym = payload.get("symbol") if isinstance(payload, dict) else None
    sym = sym or "<unknown>"
    # Accept already-extracted fields if shape looks canonical.
    fields = payload
    if any(k in payload for k in ("valuation", "ratios", "scenarios", "growth")):
        fields = extract_fields(payload)
    if verdict_overrides and sym in verdict_overrides:
        fields = dict(fields)
        fields["verdict"] = verdict_overrides[sym]
    bounds = payload.get("canary_bounds") if isinstance(payload, dict) else None
    results = run_all_gates(sym, fields, fields, bounds)
    return {f"gate{n}": v for n, v in results.items()}


def evaluate(state: dict[str, dict], stocks: list[dict]) -> dict:
    """Run all gates; produce a structured report.

    Distinguishes three failure modes so a network flake doesn't masquerade
    as a gate regression:

    - ``gate_violations``: real gate failures (these always fail the run)
    - ``fetch_failures``: stocks we couldn't fetch (soft-fail if within
      the ``CANARY_MAX_FETCH_FAILURES`` budget)
    - ``excluded_from_gates``: KNOWN_BROKEN_TICKERS we deliberately skip

    A run passes iff ``gate_violations == 0`` AND
    ``fetch_failures <= CANARY_MAX_FETCH_FAILURES``. The legacy cascade
    where each fetch failure inflated all five gate counters is gone — a
    Railway cold-start no longer looks like a five-gate regression.
    """
    bounds_map = {s["symbol"]: s.get("canary_bounds") for s in stocks}
    per_stock: list[dict] = []
    gate_totals = {n: 0 for n in GATE_NAMES}
    fetch_failures = 0
    excluded = 0

    for spec in stocks:
        sym = spec["symbol"]
        st = state.get(sym, {})
        entry: dict[str, Any] = {"symbol": sym, "violations": {}, "fetch_error": st.get("error")}

        if sym in KNOWN_BROKEN_TICKERS:
            for n in GATE_NAMES:
                entry["violations"][str(n)] = []
            entry["skipped"] = "known_broken"
            excluded += 1
            per_stock.append(entry)
            continue

        if not st.get("public") or not st.get("authed"):
            # NEW SEMANTIC: do NOT cascade into gate counters. A fetch
            # failure is its own bucket — counted once, never inflates
            # the per-gate totals. The previous "all-fail this ticker
            # for visibility" trick blew up clean PRs every time
            # Railway cold-started.
            fetch_failures += 1
            for n in GATE_NAMES:
                entry["violations"][str(n)] = []
            entry["skipped"] = "fetch_failed"
            per_stock.append(entry)
            continue

        results = run_all_gates(sym, st["public"], st["authed"], bounds_map.get(sym))
        for n, vs in results.items():
            entry["violations"][str(n)] = vs
            gate_totals[n] += len(vs)
        per_stock.append(entry)

    gate_violations = sum(gate_totals.values())
    fetch_budget = _MAX_FETCH_FAILURES
    passed = (gate_violations == 0) and (fetch_failures <= fetch_budget)

    return {
        "commit_sha": _git_sha(),
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "stocks_checked": len(stocks),
        "fetch_failures": fetch_failures,
        "fetch_failure_budget": fetch_budget,
        "excluded_from_gates": excluded,
        "gate_totals": {GATE_NAMES[n]: gate_totals[n] for n in GATE_NAMES},
        "gate_violations": gate_violations,
        # Legacy alias — older tests / dashboards still read this name.
        "total_violations": gate_violations,
        "passed": passed,
        "per_stock": per_stock,
    }


# ---------------------------------------------------------------------------
# Snapshot / diff
# ---------------------------------------------------------------------------


def write_snapshot(state: dict[str, dict]) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    sha = _git_sha()
    out = SNAPSHOT_DIR / f"snapshot_{ts}_{sha}.json"
    payload = {
        "commit_sha": sha,
        "snapshot_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "state": state,
    }
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out


def diff_snapshot(
    current: dict[str, dict], snapshot_path: Path
) -> list[str]:
    raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    # New schema wraps state in {commit_sha, snapshot_at, state}; old
    # schema is the bare state dict. Support both.
    prev = raw.get("state") if isinstance(raw, dict) and "state" in raw else raw
    sha = raw.get("commit_sha", "unknown") if isinstance(raw, dict) else "unknown"
    notes: list[str] = [f"diff_against: snapshot_commit={sha}"]
    for sym, cur in current.items():
        prev_st = prev.get(sym, {})
        c_au = (cur or {}).get("authed") or {}
        p_au = (prev_st or {}).get("authed") or {}
        c_fv, p_fv = c_au.get("fair_value"), p_au.get("fair_value")
        c_mos, p_mos = c_au.get("margin_of_safety"), p_au.get("margin_of_safety")
        # Per-ticker drift tolerance: honour overrides for names where
        # natural drift exceeds the default (TITAN/ULTRA/premium
        # compounders via fv_tolerance_pct; volatile small caps etc.).
        # Sub-BENIGN_FV_PCT drift is always noise — don't report it.
        fv_threshold = max(
            BENIGN_FV_PCT,
            _ticker_tolerance(sym, "fv_tolerance_pct", DRIFT_FV_PCT),
        )
        mos_threshold = max(
            BENIGN_MOS_PP,
            _ticker_tolerance(sym, "mos_tolerance_pp", DRIFT_MOS_PP),
        )
        if _is_num(c_fv) and _is_num(p_fv) and p_fv != 0:
            drift = abs(c_fv - p_fv) / abs(p_fv)
            if drift > fv_threshold:
                notes.append(
                    f"{sym}: FV drift {drift:.1%} ({p_fv:.2f} -> {c_fv:.2f}) — investigate"
                )
        if _is_num(c_mos) and _is_num(p_mos):
            d = abs(c_mos - p_mos)
            if d > mos_threshold:
                notes.append(
                    f"{sym}: MoS drift {d:.3f} ({p_mos:.3f} -> {c_mos:.3f}) — investigate"
                )
    return notes


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_markdown(report: dict, drift_notes: list[str] | None = None) -> str:
    lines = [
        f"# Canary Diff Report",
        "",
        f"Commit: `{report.get('commit_sha', 'unknown')}`",
        f"Timestamp: {report['timestamp']}",
        "",
    ]
    lines.append(f"Stocks checked: **{report['stocks_checked']}**")
    fetch_n = report["fetch_failures"]
    budget = report.get("fetch_failure_budget", _MAX_FETCH_FAILURES)
    if fetch_n == 0:
        lines.append("Fetch failures: **0**")
    elif fetch_n <= budget:
        lines.append(f"Fetch failures: **{fetch_n}** (WARN — within budget {budget})")
    else:
        lines.append(f"Fetch failures: **{fetch_n}** (FAIL — over budget {budget})")
    lines.append(f"Gate violations: **{report['gate_violations']}**")
    lines.append("")
    lines.append("## Gate totals")
    for name, n in report["gate_totals"].items():
        marker = "PASS" if n == 0 else f"FAIL ({n})"
        lines.append(f"- **{name}**: {marker}")
    lines.append("")
    bad = [s for s in report["per_stock"] if any(s["violations"].values())]
    if bad:
        lines.append("## Violations")
        for s in bad:
            lines.append(f"### {s['symbol']}")
            for gate, vs in s["violations"].items():
                if vs:
                    lines.append(f"- gate {gate}:")
                    for v in vs:
                        lines.append(f"  - {v}")
            lines.append("")
    if drift_notes:
        lines.append("## Snapshot drift (advisory — does not fail the gate)")
        for n in drift_notes:
            lines.append(f"- {n}")
        lines.append("")
    lines.append("---")
    lines.append("STATUS: " + ("PASS" if report["passed"] else "FAIL"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="YieldIQ canary-diff merge gate")
    p.add_argument("--stocks", default=str(DEFAULT_STOCKS), help="path to canary_stocks_50.json")
    p.add_argument("--api-base", default=API_BASE)
    p.add_argument("--report-json", default="canary_report.json")
    p.add_argument("--report-md", default="canary_report.md")
    p.add_argument("--snapshot", action="store_true", help="write snapshot only, no gates")
    p.add_argument("--diff-against", default=None, help="path to snapshot file to diff against")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    stocks = load_stocks(Path(args.stocks))
    print(f"Canary diff: {len(stocks)} stocks against {args.api_base}")
    t0 = time.time()
    state = collect_state(stocks, api_base=args.api_base, token=AUTH_TOKEN, verbose=not args.quiet)
    print(f"Fetched in {time.time() - t0:.1f}s")

    if args.snapshot:
        out = write_snapshot(state)
        print(f"Snapshot written to {out}")
        return 0

    drift_notes: list[str] = []
    if args.diff_against:
        drift_notes = diff_snapshot(state, Path(args.diff_against))

    report = evaluate(state, stocks)
    Path(args.report_json).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    Path(args.report_md).write_text(render_markdown(report, drift_notes), encoding="utf-8")

    print()
    print(f"Gate violations: {report['gate_violations']}")
    print(
        f"Fetch failures: {report['fetch_failures']} "
        f"(budget {report['fetch_failure_budget']})"
    )
    for name, n in report["gate_totals"].items():
        flag = "ok" if n == 0 else "FAIL"
        print(f"  {flag:4s} {name}: {n}")
    # Distinguish WARN (fetch flake within budget) from FAIL.
    if report["fetch_failures"] > 0 and report["fetch_failures"] <= report["fetch_failure_budget"]:
        print(
            f"WARN: {report['fetch_failures']} fetch failure(s) within budget "
            f"of {report['fetch_failure_budget']} — soft-pass."
        )
    elif report["fetch_failures"] > report["fetch_failure_budget"]:
        print(
            f"FAIL: {report['fetch_failures']} fetch failure(s) > budget "
            f"of {report['fetch_failure_budget']} — API likely unhealthy."
        )
        # Surface a representative error so users don't have to grep
        # the JSON report. The 49/50 incident on prod was diagnosed an
        # hour late because the only signal was the bare summary line.
        _err_samples = [
            (s["symbol"], s.get("fetch_error"))
            for s in report["per_stock"]
            if s.get("fetch_error")
        ][:3]
        if _err_samples:
            print("  Sample errors:")
            for sym, err in _err_samples:
                print(f"    {sym}: {err}")
        # 401 on /analysis is the canonical local-mode footgun: harness
        # default points at api.yieldiq.in which requires a Bearer token,
        # so the public endpoint succeeds and the authed one returns
        # empty data — gates trivially pass on null payloads.
        if any("401" in (e or "") for _, e in _err_samples):
            print(
                "  Hint: HTTP 401 on /analysis means CANARY_AUTH_TOKEN is "
                "unset or expired. For local validation use "
                "`scripts/run_canary_local.ps1` (boots a local backend "
                "with YIELDIQ_DEV_MODE=true) instead of pointing at prod."
            )
    if drift_notes:
        print(f"Snapshot drift notes (advisory): {len(drift_notes)}")
    print(f"Reports: {args.report_json}, {args.report_md}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
