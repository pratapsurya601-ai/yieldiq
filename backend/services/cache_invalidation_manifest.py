# backend/services/cache_invalidation_manifest.py
"""
Granular cache invalidation manifest (Day-94, 2026-05-22).

Replaces the single global CACHE_VERSION integer as the read-path
validity gate. The integer remains as a panic-switch fallback (see
CACHE_MANIFEST_DISABLED env var) and as informational metadata on
every cached row, but the manifest is the authoritative source of
truth for "is this cached row still valid?".

═══════════════════════════════════════════════════════════════
Why this exists
═══════════════════════════════════════════════════════════════

The pre-Day-94 model:
  - CACHE_VERSION is a single integer
  - Every bump invalidates EVERY cached row across EVERY ticker
  - 2,400 tickers × 20s cold yfinance recompute = ~13 hours of
    compute per bump
  - A 4-line bear-floor fix for 6 utility tickers costs the same as
    a 400-line rewrite that affects everything

Today (2026-05-22) we hit CACHE_VERSION=136 after ~21 bumps in a
12-hour window. The Railway memory chart showed spikes lining up
with each bump, and the cache_service.py header now reads:
"Today we bumped this 21 times in 12 hours and caused real latency
problems. Don't do that again."

Day-94 replaces "don't bump" discipline with an architectural fix.

═══════════════════════════════════════════════════════════════
How it works
═══════════════════════════════════════════════════════════════

A row in analysis_cache is valid IFF:
  - It was computed AFTER the most-recent invalidation that applies
    to (ticker, fields_being_read)

Where "applies" means:
  - The manifest entry's `scope.tickers` includes this ticker
    (or is "*" for global), AND
  - The manifest entry's `scope.fields` overlaps with the fields
    the caller intends to read (or is "*" for full-payload)

The matcher is O(N × M) where N is the manifest length and M is
the field count. We expect N to grow ~5/week, capped at maybe 200
entries before we add a retention policy. Cheap.

═══════════════════════════════════════════════════════════════
How to add a new invalidation
═══════════════════════════════════════════════════════════════

When you ship an engine change, append ONE entry to MANIFEST below:

    {
        "version_id": "v137_day95_xyz",
        "applied_at": datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["NTPC", "POWERGRID"],  # bare, no .NS
            "fields": ["scenarios.bear"],
        },
        "rationale": "one-line description of the fix",
    },

Field paths use dot notation matching the analysis payload shape:
  - "fair_value", "mos", "verdict", "score"
  - "scenarios.bear", "scenarios.bull", "scenarios.base"
  - "valuation.wacc", "valuation.terminal_growth"
  - "quality.moat", "quality.roe"
  - "red_flags_structured"
  - "*" for the whole payload (use sparingly — reverts to global bump)

If the fix changes the ENGINE's output for a ticker, ANY downstream
field could shift. Use ["*"] in those cases. If the fix only
changes a derived field (e.g. dividend.sustainability label which
is computed at response time, not stored), no manifest entry is
needed.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

log = logging.getLogger("yieldiq.cache_manifest")


# ─────────────────────────────────────────────────────────────────
# Task #123 (2026-05-23): public-surface sanitization.
#
# Internal cadence tokens — "Day-107a", "Phase B.1", "Audit#7",
# "PR #498", "#503" — are engineering vocabulary. Leaking them onto
# anon-facing surfaces (sector landing pages, public manifest-history
# endpoint) (a) confuses end users who have no model of our release
# cadence and (b) creates SEBI exposure: a cadence-keyed verb like
# "Day-107a applied" reads as advisory ("we changed our advice
# today") even though the underlying entry is a model-engineering
# note.
#
# Authed surfaces (the per-ticker analysis page for a logged-in
# pro / analyst user) still see the raw version_id + rationale —
# power users want the receipts and have signed up for the engineering
# vocabulary.
# ─────────────────────────────────────────────────────────────────

# Match the internal cadence / release tokens we never want surfaced
# to anon users. Patterns are intentionally permissive on the trailing
# punctuation so they sweep up "Day-107a:", "Day-107a." and bare
# "Day-107a" alike.
# Fix #566-followup (2026-05-24): the original Phase pattern only
# matched "Phase X" or "Phase X.N", but Phase G/H/I rationales use
# extended forms — "Phase G-intel-phase1 (c)", "Phase H-frontend
# (Block II)", "Phase I-frontend (Block II)" — which left the
# suffixes ("-intel-phase1 (c):", "frontend (Block II):") on the
# anon-facing surface. The new pattern sweeps the entire compound
# label:
#   * Phase <Letter>                              (e.g. "Phase F")
#   * optional dotted/hyphenated subparts         (".1", "-intel-phase1")
#   * optional adjacent paren labels              ("(c)", "(Block II)")
# The trailing-paren clause is anchored to the Phase token (no
# intervening text), so a free-standing parenthetical like the
# Day-107a rationale's "(WACC tighten, TG lift, ...)" is NOT
# consumed.
#
# Also extended PR to accept the bare "PR 1" form (no '#') because
# the Phase C.2 rationale writes "Phase C.2 PR 1: …".
_INTERNAL_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bDay-\d+[a-z]?\b", re.IGNORECASE),
    # Upstream regex (PR #622) handles "Phase X", dotted ".N",
    # hyphenated "-intel-phase1" / "-frontend", and trailing paren
    # labels like "(c)", "(Block II)" — all in one match.
    re.compile(
        r"\bPhase\s+[A-Z](?:[-.][a-zA-Z0-9]+)*(?:\s*\([a-zA-Z0-9 ]+\))*"
    ),
    # Free-standing "Block II" / "Block III" outside a Phase prefix.
    re.compile(r"\bBlock\s+[IVX]+\b"),
    re.compile(r"\bAudit\s*#\s*\d+(?:\s*P\d+[a-z]?)?\b", re.IGNORECASE),
    re.compile(r"\bPR\s*#?\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bTask\s*#\s*\d+\b", re.IGNORECASE),
    re.compile(r"#\d+\b"),
)


def _strip_internal_tokens(text: str) -> str:
    """Strip Day-/Phase/Audit#/PR#/Task#/#NNN tokens from a string.

    Collapses the punctuation/whitespace seam left behind so the
    output reads cleanly (no double spaces, no leading ": ", no
    dangling parens). Returns the empty string on falsy input.
    """
    if not text:
        return ""
    out = text
    for pat in _INTERNAL_TOKEN_PATTERNS:
        out = pat.sub("", out)
    # Collapse whitespace + tidy punctuation seams.
    out = re.sub(r"\s+", " ", out)
    # Strip ": " immediately following an opening paren, or stray
    # "()" pairs left after token removal.
    out = re.sub(r"\(\s*[:\-]\s*", "(", out)
    out = re.sub(r"\(\s*\)", "", out)
    # Drop a leading "(c):" / "(2):" sub-label left behind after
    # stripping the Phase token (e.g. "Phase G PR (c):" → "(c):").
    out = re.sub(r"^\s*\([A-Za-z0-9]{1,3}\)\s*[:\-]\s*", "", out)
    # Strip a leading colon/dash left behind by something like
    # "Day-107a: IT services" → ": IT services" OR
    # "Phase H-frontend (Block II): expose ..." after paren collapse.
    # Run this last so earlier paren cleanup gets its chance to
    # expose the leading punctuation it left behind.
    out = re.sub(r"^[\s:\-–—]+", "", out)
    # Collapse " ." / " ," seams.
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    # Collapse orphan comma runs left after token removal, e.g.
    # "(A, , B, , C)" → "(A, B, C)" and "(, A)" → "(A)".
    out = re.sub(r",(\s*,)+", ",", out)
    out = re.sub(r"\(\s*,\s*", "(", out)
    out = re.sub(r"\s*,\s*\)", ")", out)
    # One more whitespace collapse after the comma surgery.
    out = re.sub(r"\s+", " ", out)
    return out.strip()


def _public_description(entry: dict) -> str:
    """Return the SEBI-safe, anon-facing rationale for a manifest entry.

    Strips internal cadence tokens (Day-NNN, Phase X, Audit#N, PR#N,
    Task#N, #NNN). Falls back to a generic "Model updated" string
    when the cleaned text is empty (e.g. the rationale was nothing
    but a cadence tag).
    """
    raw = (entry or {}).get("rationale") or ""
    cleaned = _strip_internal_tokens(raw)
    if not cleaned:
        return "Model updated."
    # Capitalize the first letter so we don't ship sentences that
    # start lowercase after stripping a leading "Day-107a: " label.
    return cleaned[0].upper() + cleaned[1:]


def public_manifest_entry(entry: dict) -> dict:
    """Project a manifest entry into its anon-safe shape.

    Strips ``version_id`` (an internal cadence handle), replaces the
    raw ``rationale`` with the cleaned ``description``, and preserves
    ``applied_at`` + ``fields_affected`` so the timeline still has
    timing + scope context.
    """
    if not isinstance(entry, dict):
        return {"applied_at": None, "description": "Model updated.", "fields_affected": ["*"]}
    applied_at = entry.get("applied_at")
    try:
        applied_iso = applied_at.isoformat() if hasattr(applied_at, "isoformat") else (
            str(applied_at) if applied_at else None
        )
    except Exception:
        applied_iso = str(applied_at) if applied_at else None
    scope_fields = (entry.get("scope") or {}).get("fields")
    if scope_fields == "*" or scope_fields is None:
        fields_affected: list[str] = ["*"]
    elif isinstance(scope_fields, (list, tuple, set)):
        fields_affected = [str(f) for f in scope_fields]
    else:
        fields_affected = [str(scope_fields)]
    return {
        "applied_at": applied_iso,
        "description": _public_description(entry),
        "fields_affected": fields_affected,
    }


# ─────────────────────────────────────────────────────────────────
# Phase B.1 (2026-05-24) — in-memory drain on manifest apply
#
# Background. The Day-94 manifest gates Postgres-tier (tier-2) reads
# correctly: a new entry invalidates an old `analysis_cache` row on
# the next read. But three in-memory tiers bypass the manifest:
#
#   * tier-0  `analysis:{ticker}:raw`         (24 h TTL, not version-keyed)
#   * tier-1  `analysis:{ticker}`             (24 h TTL, not version-keyed)
#   * tier-5  `public:stock-summary:{ticker}` (1 h TTL,  version-keyed)
#
# A worker warmed BEFORE a cohort applies keeps serving the pre-cohort
# payload until its in-memory TTL expires. Authed (tier-0/1) and anon
# (tier-5) get different verdicts during the drift window. That is the
# concrete "auth vs anon mismatch" P0 reframed by the Phase B.0 audit
# (see docs/diagnostics/phase-b-cache-paths-2026-05-24.md).
#
# Mechanism. Drain hooks register at module import; on every fresh
# process start we sweep the manifest for entries applied in the last
# DRAIN_LOOKBACK_HOURS (default = the worst in-memory TTL, 24 h) and
# fire each hook for each recent entry. Each hook drains its own tier
# (cache_service.delete_by_prefix). The sweep is idempotent (delete on
# an empty store is a no-op) so calling drain twice is safe.
#
# Per-worker scope. Each Railway worker has its own in-memory cache —
# there is no shared store this hook can reach across processes.
# Cross-process drain would require a Postgres LISTEN/NOTIFY or a
# Redis pub/sub. The acceptable failure mode here is: every worker
# drains its own cache as soon as the new code (carrying the new
# manifest entry) is imported, which happens on every deploy and on
# every cold start. The remaining worst case is a worker that survives
# the deploy AND warmed the cache before the new entry's applied_at —
# in that case the natural ~24h TTL still applies. This is documented
# at docs/design/cache-consistency-architecture-2026-05-24.md.
# ─────────────────────────────────────────────────────────────────

#: Hooks fired for each manifest entry detected at import-time sweep.
#: Signature: ``hook(entry: dict) -> None``. Hooks must not raise.
MANIFEST_APPLIED_HOOKS: list[Callable[[dict], None]] = []

#: How far back to look for "recently applied" entries on a process
#: start. Tuned to the worst in-memory TTL (analysis:{ticker}:raw = 24h)
#: so we cover the full possible stale window.
DRAIN_LOOKBACK_HOURS = 24


def register_manifest_applied_hook(hook: Callable[[dict], None]) -> None:
    """Register a callable invoked once per recent manifest entry on
    import-time sweep.

    Idempotent: registering the same callable twice still results in
    it being stored twice, but the underlying drain operation is itself
    idempotent (delete-on-empty is a no-op).
    """
    MANIFEST_APPLIED_HOOKS.append(hook)


def notify_manifest_entry_applied(entry: dict) -> None:
    """Fire every registered hook for a single manifest entry. Hook
    exceptions are caught and logged so one misbehaving hook can't
    take down the others (or the import).
    """
    for hook in MANIFEST_APPLIED_HOOKS:
        try:
            hook(entry)
        except Exception as exc:  # noqa: BLE001 — defensive
            log.warning(
                "cache_manifest: hook %r raised on entry %s: %s",
                getattr(hook, "__name__", repr(hook)),
                (entry or {}).get("version_id"),
                exc,
            )


# ─────────────────────────────────────────────────────────────────
# Panic switch
#
# Set CACHE_MANIFEST_DISABLED=1 in the environment to fall back to
# the legacy "strict cache_version equality" behavior. Use only if
# the manifest produces obviously-wrong cache hits in prod.
# ─────────────────────────────────────────────────────────────────
_DISABLED = os.environ.get("CACHE_MANIFEST_DISABLED", "").strip() in ("1", "true", "yes")


# ─────────────────────────────────────────────────────────────────
# The manifest itself
#
# Append-only. Newest entries at the bottom. Entry order doesn't
# affect correctness (the matcher iterates all entries) but
# chronological order makes the diff history readable.
# ─────────────────────────────────────────────────────────────────
MANIFEST: list[dict] = [
    {
        # T5.7 — monthly accuracy report cron added. Runs 1st of each
        # month and computes 30-day-forward direction accuracy +
        # magnitude error per ticker for everything published in the
        # prior calendar month, then writes a snapshot the
        # /calibration page links to and emails the operator. Pure
        # observability — no engine output changes — so scope.fields
        # is empty (no cache rows need invalidation).
        "version_id": "v_t5_7_monthly_accuracy_report_2026_06_10",
        "applied_at": datetime.now(timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": [],
        },
        "rationale": (
            "T5.7 — monthly accuracy report cron added. Runs 1st of "
            "each month. Computes 30-day-forward direction accuracy "
            "and magnitude error per ticker. Outputs to operator "
            "email + /calibration page snapshot."
        ),
    },
    {
        # Issue #204 — service-layer derivation of operating_income for
        # banks (Schedule III Div I doesn't carry a single op-income line;
        # we derive it from interest_earned − interest_expended +
        # non_interest_income − operating_expenses). Bumps any cached row
        # that surfaced a NULL operating_income / operating_margin for a
        # bank so the new derived value flows. Scope is "*" (wildcard)
        # because bank tickers vary by the sector_overrides taxonomy and
        # enumerating them in the manifest entry is more error-prone than
        # the cheap revalidation on next read.
        "version_id": "v_bank_op_income_derive_2026_06_07",
        "applied_at": datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": [
                "operating_income",
                "ebit_margin",
                "interest_coverage",
            ],
        },
        "rationale": (
            "Issue #204: derive operating_income for banks at the service "
            "layer from interest_earned/expended + non-interest income − "
            "operating expenses so EBIT margin + interest coverage stop "
            "rendering NULL on the Schedule III Div I bank cohort."
        ),
    },
    {
        # Tickertape density trick #2 (audit
        # .audit/tickertape-deep-walk-2026-05-27.md). The analysis
        # response now carries `sector_medians` (5 cohort medians:
        # pe/pb/roe/div_yield/op_margin) so the frontend can render
        # "Sector X" chips beside every primary ratio. The field is
        # injected at the router boundary on every cache tier so warm
        # rows surface the chip context without a CACHE_VERSION bump.
        # Scope-narrow because no existing field changes — purely
        # additive surface that pre-PR cached payloads also receive
        # via the injection path.
        "version_id": "v_sector_medians_in_analysis_payload",
        "applied_at": datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["sector_medians"]},
        "rationale": (
            "Inline sector-median chips on every primary metric — "
            "context-by-default per Tickertape density trick #2."
        ),
    },
    {
        "version_id": "v_worry_comparison_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 17, 30, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["worry_index", "peer_context"]},
        "rationale": (
            "Worry Index emotional score + inline comparison sliders on "
            "every key metric — context-by-default."
        ),
    },
    {
        # The migration anchor. Every cached row predating this
        # entry's applied_at gets invalidated once — final global
        # wipe. From this point forward, all bumps are scoped.
        "version_id": "v_init_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 23, 0, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": "*"},
        "rationale": (
            "Day-94 migration anchor — invalidate everything predating "
            "the manifest deploy so the system starts from a clean state."
        ),
    },
    {
        "version_id": "v_day95_metals_sector_pins",
        "applied_at": datetime(2026, 5, 22, 4, 50, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "HINDZINC", "HINDCOPPER", "HINDALCO", "VEDL", "NATIONALUM",
                "TATASTEEL", "JSWSTEEL", "JINDALSTEL", "SAIL", "NMDC",
                "MOIL", "GMDCLTD", "COALINDIA", "WELCORP", "RATNAMANI",
                "APLAPOLLO", "JINDALSAW",
            ],
            "fields": "*",  # sector pin can shift anything downstream
        },
        "rationale": "Day-95: metals/mining sector pins (HINDZINC and 16 others). Cohort routing change.",
    },
    {
        # Day-100 / Audit #5 P0b — fair_value 0-floor leak.
        # `_extract_analysis_summary` in backend/routers/public.py used
        # to forward the engine's fair_value verbatim. When the engine
        # returned 0.0 but a real scenario midpoint (base_case) existed
        # (ULTRACEMCO.NS at 2026-05-22), the SEO fair-value page rendered
        # "₹0 fair value" on the hero pill. Fix: fall through to
        # base_case when engine fair_value is 0 and base_case > 0; emit
        # None when neither exists so the frontend hides the pill.
        "version_id": "v_audit5_p0b_fv_floor_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["ULTRACEMCO"],
            "fields": ["fair_value"],
        },
        "rationale": (
            "Audit#5 P0b: fair_value 0-floor leak — fall through to "
            "base_case in /stock-summary projection so the SEO hero "
            "pill stops rendering ₹0 when the engine collapses but "
            "scenario midpoint is meaningful."
        ),
    },
    {
        # Audit#5 P1: INDIGO asset_turnover=359808 — clearly a unit
        # mismatch. Defensive sanity gate in compute_asset_turnover
        # nulls values outside [0.001, 100] so UI shows "n/a" instead
        # of an obviously-wrong number.
        "version_id": "v_audit5_p1_asset_turnover_units_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 13, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["INDIGO"],
            "fields": ["ratios.asset_turnover"],
        },
        "rationale": (
            "Audit#5 P1: asset_turnover sanity gate — INDIGO showed "
            "359808 due to unit mismatch upstream. Scoped to INDIGO; "
            "other tickers are within plausible band."
        ),
    },
    {
        # Audit#5 P1: de_ratio=0 on all 17 audit-universe tickers.
        # Root cause: data/collector.py coerced missing yfinance
        # debtToEquity to 0 instead of None. Fix reads from
        # ratio_history (XBRL) and preserves None for genuine missing.
        "version_id": "v_audit5_p1_de_ratio_null_safety_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 13, 30, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["ratios.de_ratio"],
        },
        "rationale": (
            "Audit#5 P1: de_ratio null-safety — every audit-universe "
            "ticker was casting yfinance null to literal 0. Read from "
            "ratio_history first; reject implausible zero when debt > 0."
        ),
    },
    {
        # Task#87: asset_turnover=null for RELIANCE/TATASTEEL/
        # ULTRACEMCO/TCS/INFY. PR #498's sanity gate was correctly
        # rejecting a ~1e-7 ratio caused by a pre-existing unit
        # mismatch at the call site in analysis/service.py — revenue
        # in Crores vs total_assets in raw INR (yfinance). Fix mirrors
        # the FIX-ROCE-UNIT-MISMATCH pattern: prefer DB _ta_db (Crores)
        # so units align with revenue.
        "version_id": "v_task87_asset_turnover_unit_callsite_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 15, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["ratios.asset_turnover"],
        },
        "rationale": (
            "Task#87: asset_turnover call site mixed Crore revenue "
            "with raw-INR total_assets, producing ~1e-7 ratios that "
            "PR #498's sanity gate correctly nulled. Prefer DB total "
            "assets so units match revenue."
        ),
    },
    {
        # Audit#6: backend mirror of frontend PR #499 — asymmetric
        # bear-side bypass for the overvalued band. Layer-3 of
        # _apply_confidence_verdict_gate was capping any moderate-
        # confidence overvalued read down to fairly_valued; the
        # frontend already corrected this in the UI rendering layer,
        # so the API payload disagreed with the rendered pill on a
        # subset of bear-side tickers. Fix mirrors the frontend
        # constants (BEAR_OVERVALUED_BYPASS_MOS=-25,
        # BEAR_OVERVALUED_BYPASS_CONFIDENCE=40,
        # BEAR_NOTABLY_OVERVALUED_MOS=-40) into the gate so the
        # backend ``verdict`` field agrees with the UI label.
        "version_id": "v_audit6_backend_overvalued_mirror_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 16, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["SUNPHARMA", "MARUTI", "SBIN", "ASIANPAINT"],
            "fields": ["verdict"],
        },
        "rationale": (
            "Audit#6: backend mirror of #499 frontend overvalued gate. "
            "Re-derives verdict for the four audit-confirmed bear-side "
            "tickers so /api/v1/public/stock-summary, og-data, push and "
            "email alerts, and verdict-keyed analytics agree with the "
            "rendered pill."
        ),
    },
    {
        # Audit#7 P0 (2026-05-22): the Audit#6 bypass above returned
        # "notably_overvalued" when mos_pct <= -40. ValuationOutput.verdict
        # in backend/models/responses.py is Literal[undervalued,
        # fairly_valued, overvalued, avoid, data_limited, unavailable] and
        # does NOT include "notably_overvalued". Pydantic raised
        # ValidationError inside get_full_analysis, the public
        # stock-summary endpoint caught it in the cache-miss recompute
        # path (backend/routers/public.py:672) and started returning the
        # opaque "cache_miss_recompute_failed" placeholder for every
        # ASIANPAINT.NS request. SUNPHARMA / MARUTI / SBIN escaped the
        # bug because their MoS (-33, -31, -31) is above the -40
        # BEAR_NOTABLY_OVERVALUED_MOS boundary, so they returned plain
        # "overvalued" (a valid literal) and recomputed cleanly.
        #
        # Fix: clamp the bypass output to "overvalued" and log the
        # intensity hint in the issues array. Frontend pill rendering
        # is unaffected because it derives the label from mos_pct via
        # verdictFromMos on the client, not from this string.
        "version_id": "v_audit7_p0_asianpaint_recompute_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 16, 30, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["ASIANPAINT"],
            "fields": ["*"],
        },
        "rationale": (
            "Audit#7 P0: ASIANPAINT.NS summary recompute wedged on "
            "cache_miss_recompute_failed after Audit#6 (PR #503). The "
            "bypass returned 'notably_overvalued' which is not a valid "
            "ValuationOutput.verdict literal, pydantic raised, the "
            "recompute fell through to the under_review placeholder. "
            "Clamp to 'overvalued' so the response validates. Scoped "
            "to ASIANPAINT (the only ticker with mos_pct deep enough "
            "to cross the unmodeled branch)."
        ),
    },
    {
        # Day-103c (2026-05-22): added `compounded_growth` field to
        # /api/v1/public/stock-summary response (3y/5y/10y CAGR panel
        # for revenue/profit/ROE-avg/stock). Pure additive surface —
        # no existing field changed. Manifest entry exists so any
        # stock-summary rows cached before the deploy get refreshed
        # and start emitting the new field.
        "version_id": "v_day103c_cagr_panel_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 19, 0, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["compounded_growth"]},
        "rationale": "Day-103c: new compounded_growth field on stock-summary",
    },
    {
        # Day-107a (2026-05-23): IT services cohort overrides
        # (Tier-1 WACC cap 0.115, Tier-2 0.125, hard floor 0.085;
        # backwards-compat band ±20% on TCS/INFY DCF math).
        "version_id": "v_day107a_it_services_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 10, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM",
                        "LTIM", "PERSISTENT", "MPHASIS", "COFORGE", "BSOFT"],
            "fields": "*",
        },
        "rationale": (
            "Day-107a: IT services cohort overrides (WACC tighten, TG "
            "lift, scenario re-weight)"
        ),
    },
    {
        # Day-107c (2026-05-23): Indian auto OEM cohort overrides.
        # Segment-differentiated TG (2W 5.0%, 4W 4.5%, CV 4.0%,
        # ancillary 4.0%), ASHOKLEY CV WACC floor 0.11, cycle-trough
        # bear-floor `min(0.6*fv, 0.4*price)` triggered when trailing
        # EBITDA margin < 50% of 5y median.
        "version_id": "v_day107c_auto_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 10, 10, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO",
                "HEROMOTOCO", "EICHERMOT", "ASHOKLEY", "TVSMOTOR",
                "MOTHERSON", "BOSCHLTD", "MRF", "APOLLOTYRE",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-107c: auto cohort overrides (5y EBIT normalization, "
            "segment TG, cycle bear-floor)"
        ),
    },
    {
        # Day-107b (2026-05-23): FMCG sector cohort overrides — TG
        # lift to 5.0%/4.5%/4.5%/4.0% by tier, WACC floor 8.5%,
        # moat-pillar floor 75 for top-4, scenario weighting 40/40/20.
        "version_id": "v_day107b_fmcg_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 10, 5, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "HUL", "NESTLEIND", "ITC", "BRITANNIA", "DABUR",
                "MARICO", "COLPAL", "GODREJCP", "EMAMI",
                "TATACONSUM", "VBL",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-107b: FMCG cohort overrides (TG lift, WACC tighten, "
            "moat premium)"
        ),
    },
    {
        # Day-107d (2026-05-23): Capital Goods / E&C cohort overrides.
        # Sub-buckets: defence+power-T&D (BEL/ABB/SIEMENS) TG 4.5%,
        # general E&C TG 4.0%, BHEL TG 3.5% + 50bps WACC penalty.
        # Order-book lift deferred to Phase 2 pending order_book col.
        "version_id": "v_day107d_capital_goods_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 10, 15, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "LT", "SIEMENS", "ABB", "CUMMINSIND", "BHEL", "BEL",
                "THERMAX", "KEC", "VOLTAS", "BLUESTARCO",
                "KIRLOSKAR", "GRINDWELL",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-107d: capital goods cohort overrides (order-book lift "
            "deferred to Phase 2, TG by sub-segment 4.5/4.0/3.5%, "
            "BHEL +50bps WACC penalty)."
        ),
    },
    {
        # Day-109b (2026-05-23): NBFC sub-segment PB anchoring.
        "version_id": "v_day109b_nbfc_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 20, 5, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "BAJFINANCE", "LICHSGFIN", "PNBHOUSING", "REPCO",
                "MUTHOOTFIN", "MANAPPURAM", "CREDITACC", "CHOLAFIN",
                "MMFIN", "SHRIRAMFIN", "SUNDARMFIN",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-109b: NBFC cohort PB anchoring by sub-segment + "
            "AUM-growth boost"
        ),
    },
    {
        # Day-110b (2026-05-23): Insurance cohort overrides (P/EV
        # anchors for life — P/B fallback today, P/EV when EV
        # ingestion lands; P/B + CR overlay for general insurance).
        "version_id": "v_day110b_insurance_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 21, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "HDFCLIFE", "SBILIFE", "ICICIPRULI", "LICI", "MAXFIN",
                "ICICIGI", "NIACL",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-110b: Insurance cohort overrides (P/EV anchors for "
            "life, P/B+CR for general)"
        ),
    },
    {
        # Day-110a (2026-05-23): observability-only manifest entry for
        # the sector landing-page read-path hotfix (aggregator now uses
        # get_cached_latest() which bypasses manifest validation).
        "version_id": "v_day110a_sector_page_read_path_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 11, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["sector_page"],
        },
        "rationale": (
            "Day-110a: sector landing-page aggregator now bypasses "
            "manifest validation (read-path-only)."
        ),
    },
    {
        # Day-109a (2026-05-23): Banking sector cohort overrides.
        # Layered on Day-76 PB skip path: tier-anchored P/BV (T1 3.0x,
        # PSU 1.2x, T2 1.8x), ROE-quality boost, stress flag.
        "version_id": "v_day109a_banking_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 20, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK",
                "SBIN", "INDUSINDBK", "FEDERALBNK", "IDFCFIRSTB",
                "AUBANK", "BANDHANBNK", "RBLBANK",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-109a: banking cohort PB anchoring + ROE-quality "
            "boost + stress flag"
        ),
    },
    {
        # Day-110c (2026-05-23): REIT/InvIT sector cohort overrides.
        # Distribution-yield-anchored implied fair price by
        # sub-segment (office/retail REIT, roads/transmission/other
        # InvIT). Layered on PR #333 REIT short-circuit; InvITs join
        # the same no-DCF path via the new is_invit classifier. Adds
        # ``reit_invit_cohort`` block to _computation_inputs.
        "version_id": "v_day110c_reit_invit_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 21, 5, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "EMBASSY", "MINDSPACE", "BIRET", "BROOKFIELD",
                "NEXUSSELECT", "NEXUS",
                "IRBINVIT", "POWERGRIDIT", "INDIGRID", "VIRTUS",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-110c: REIT/InvIT distribution-yield anchoring by "
            "sub-segment"
        ),
    },
    {
        # Day-111c (2026-05-23): bull-side symmetric verdict bypass.
        # Mirrors bear-side Audit#6 rule. Fixes 19 verdict-mismatch
        # tickers (LICI at +95% MoS was labeled "fairly_valued").
        "version_id": "v_day111c_bull_undervalued_bypass_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 22, 10, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["verdict"]},
        "rationale": (
            "Day-111c: bull-side symmetric bypass to fix verdict "
            "mismatch when MoS >= 50% (LICI at 95% MoS was labeled "
            "fairly_valued)."
        ),
    },
    {
        # Day-112 (2026-05-23): robust adj_close infrastructure.
        # cagr_service.py now reads adj_close (split/bonus/dividend
        # adjusted) instead of raw close_price. Affects compounded_
        # growth.stock.{3y,5y,10y} on every ticker AND adds a new
        # compounded_growth.stock.status field ("ok" / "partial" /
        # "rebuild_pending" / "db_unavailable"). Scoped to those two
        # field families so other cached payload sections (DCF, ratios,
        # verdict) aren't touched.
        #
        # Tickers: "*" because the broken populator wrote close into
        # adj_close for every ticker — every cached stock-CAGR cell
        # needs re-emission once the rebuild script runs against prod
        # daily_prices.
        "version_id": "v_day112_adj_close_rebuild_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 23, 30, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["compounded_growth.stock", "stock_cagr_status"],
        },
        "rationale": (
            "Day-112: cagr_service.py switched from close_price to "
            "adj_close (split/bonus adjusted); new stock_cagr_status "
            "field surfaces rebuild_pending."
        ),
    },
    {
        # Phase B.1 (2026-05-24): in-memory drain on manifest apply.
        # This entry exists to mark the deploy that wires the drain
        # hook. On every fresh worker start from this commit forward,
        # the import-time sweep will drain analysis:* and
        # public:stock-summary:* before serving the first request,
        # closing the auth-vs-anon drift window documented in
        # docs/diagnostics/phase-b-cache-paths-2026-05-24.md.
        #
        # Scope is intentionally narrow (the four headline fields the
        # auth/anon divergence affects) so the entry doesn't force a
        # tier-2 recompute on payloads that are otherwise still valid;
        # the drain itself fires on the wildcard prefix regardless of
        # scope.fields, but the manifest-row gate stays surgical.
        "version_id": "v_day113_phase_b1_inmem_drain_2026_05_24",
        "applied_at": datetime(2026, 5, 24, 0, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["score", "verdict", "fair_value", "mos_pct"],
        },
        "rationale": (
            "Phase B.1: drain in-memory analysis:* and "
            "public:stock-summary:* on every worker start so cohort "
            "applies propagate within seconds instead of waiting on "
            "the 24h in-memory TTL."
        ),
    },
    {
        # Phase B.2 (2026-05-24): bull_case sanity gate + Day-111c
        # threshold tune. Fixes (a) IT-services WIPRO/HCLTECH/TECHM
        # showing data_limited because the Day-107a WACC drop
        # (0.1114 → 0.098) ballooned bull_case to ~33× CMP, tripping
        # the safety net into a Tier-2 rescue path that had no usable
        # cohort, and (b) HDFCBANK staying fairly_valued at +43% MoS
        # because the bull-side Day-111c bypass threshold was set at
        # 50% rather than 40%. See docs/diagnostics/
        # phase-b-cache-paths-2026-05-24.md §4 / §3.
        #
        # Tickers: "*" because the bull-clamp affects ANY generic-DCF
        # ticker whose bull > 5× CMP (potentially more than just the
        # three IT names — every cohort that ever gets a low-WACC
        # tweak in the future) and the verdict tune affects every
        # ticker in the +40–50% MoS band at moderate confidence.
        "version_id": "v_phase_b2_bull_sanity_2026_05_24",
        "applied_at": datetime(2026, 5, 24, 0, 30, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["verdict", "bull_case", "base_case", "bear_case", "data_issues"],
        },
        "rationale": (
            "Phase B.2: bull_case sanity gate (clamp at 5x CMP when "
            "broken-low-WACC inflates DCF) + Day-111c bull-side "
            "undervalued bypass threshold lowered 50 → 40."
        ),
    },
    {
        # Phase C.3 (2026-05-25): field-additive score_breakdown.
        # New `quality.score_breakdown` object on the analysis
        # response surfaces the components + MoS-dominance cap
        # modifier the frontend "Why this score?" panel reads.
        # Numeric `yieldiq_score` is UNCHANGED — this is purely a
        # transparency surface for state that was previously logged
        # but never returned. Scope narrowed to score_breakdown so
        # cohort recomputes aren't forced.
        "version_id": "v_phase_c3_score_breakdown_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 2, 0, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["score_breakdown"]},
        "rationale": (
            "Phase C.3: add quality.score_breakdown (additive only) "
            "for the 'Why this score?' transparency panel."
        ),
    },
    {
        # Phase C.2 PR 2 (2026-05-25): hard-import the canonical
        # compute_yieldiq_score in backend/services/analysis/service.py.
        # The prior try/except wrapped a MOCK with different weights
        # (40/30/20/10, no moat awareness) under the same symbol name.
        # See docs/diagnostics/phase-c-score-formula-2026-05-25.md §4
        # Quirk #3. The dashboard package ships in the backend image
        # so the import has always succeeded in production — this is
        # a cleanup that eliminates a silent divergence path.
        #
        # Scope: ["score"] because the change only affects the score
        # field and only on the unreachable mock-fallback branch.
        "version_id": "v_phase_c2_remove_mock_fallback_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 1, 0, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["score"]},
        "rationale": (
            "Phase C.2 PR 2: hard-import canonical scoring; drop "
            "divergent mock-fallback symbol."
        ),
    },
    {
        # Phase C.2 PR 1 (2026-05-25): remove TypeError fallback in
        # backend/services/analysis/service.py that ran a DIFFERENT
        # scoring formula (40/30/20 envelopes, no sentiment) than the
        # canonical compute_yieldiq_score (20/50/20/10). The fallback
        # is unreachable under realistic inputs post-2026-04-30
        # hardening — see docs/diagnostics/phase-c-score-formula-
        # 2026-05-25.md §4 Quirk #2. The new behaviour returns
        # score=0/grade=D on the (expected-impossible) TypeError path
        # rather than silently producing a divergent number.
        #
        # Scope: ["score"] because the change ONLY affects the score
        # field, and only in the unreachable TypeError branch. No
        # canary FV/verdict movement expected.
        "version_id": "v_phase_c2_remove_typeerror_fallback_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 0, 0, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["score"]},
        "rationale": (
            "Phase C.2 PR 1: drop divergent TypeError scoring fallback "
            "(canonical compute_yieldiq_score is the only score path)."
        ),
    },
    {
        # Day-111a (2026-05-23): industry serializer key fix — `industry`
        # was being dropped at the local-data assembler so cached rows
        # had `industry=""` even when the DB column was populated. The
        # serializer now passes both `sector` and `industry` through.
        # No CACHE_VERSION bump; invalidation rides on this manifest
        # entry. Cohort code reads `industry` so cached pre-fix rows
        # mis-classify (e.g. NBFC banks fall back to generic bank
        # cohort). Scope is wildcard tickers + the two fields that
        # depend on the serializer output.
        #
        # Fix #139 (2026-05-26): manifest entry was omitted when the
        # Day-111a PR landed; tests in test_day111a_industry_serializer.py
        # have been failing on main since then. Backfilling the entry
        # to match the test expectations + the original intent.
        "version_id": "v_day111a_industry_serializer_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 22, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["industry", "sector"],
        },
        "rationale": (
            "Day-111a: industry serializer key fix — pass both sector "
            "and industry through the local-data assembler so cohort "
            "routing reads the right field."
        ),
    },
    {
        # Day-111b (2026-05-23): bank D/E ratio fix — pure-bank tickers
        # were computing D/E using `total_debt / total_equity` which
        # excluded customer deposits + borrowings (the bulk of a bank's
        # liabilities). The fix routes pure-bank tickers through a
        # liabilities-based D/E that includes deposits + borrowings,
        # matching how analysts read bank leverage.
        #
        # Fix #139 (2026-05-26): manifest entry was omitted when the
        # Day-111b PR landed; tests in test_day111b_bank_de_ratio.py
        # have been failing on main since then. Backfilling the entry
        # with the scope the tests expect.
        "version_id": "v_day111b_bank_de_with_deposits_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 22, 5, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN",
                "INDUSINDBK", "FEDERALBNK", "IDFCFIRSTB", "AUBANK",
                "BANDHANBNK", "RBLBANK", "BANKBARODA", "PNB",
            ],
            "fields": ["de_ratio"],
        },
        "rationale": (
            "Day-111b: pure-bank D/E denominator switched to "
            "liabilities (deposits + borrowings + other) so the ratio "
            "matches how analysts read bank leverage."
        ),
    },
    {
        # Phase F (2026-05-25): 10-year historical depth backfill for
        # top-500 / canary-333. F.2 backfilled daily_prices.adj_close
        # via yfinance period="max" with INSERT-or-UPDATE semantics.
        # F.3 backfilled the financials table from BSE Peercomp (annual
        # + quarterly) with browser fallback for Akamai-blocked tickers.
        # F.4 regenerated ratio_history off the new financials.
        #
        # Scope is wildcard tickers + the depth-sensitive fields. Any
        # cached row computed before this entry's applied_at is invalid
        # for these fields and will be recomputed against the deeper
        # history on first read.
        "version_id": "v_phase_f_historical_depth_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 0, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": [
                "cagr_3y", "cagr_5y", "cagr_10y",
                "ratio_history", "compounded_growth",
            ],
        },
        "rationale": (
            "Phase F: 10y historical backfill (adj_close + financials "
            "+ ratios) for top-500 / canary-333."
        ),
    },
    {
        "version_id": "v_phase_g_intel_signals_2026_05_26",
        "applied_at": datetime(2026, 5, 26, 0, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["concall_signals", "concall_intel"],
        },
        "rationale": (
            "Phase G-intel-phase1 (c): expose Anthropic-extracted "
            "concall_signals on the public analysis surface."
        ),
    },
    {
        # Phase H-frontend (Block II): expose Anthropic-extracted AR
        # signals on the public analysis surface. Scoped to the new
        # ar_signals / ar_intel fields so existing cached score /
        # verdict rows are untouched -- this is purely additive.
        "version_id": "v_phase_h_ar_signals_2026_05_26",
        "applied_at": datetime(2026, 5, 26, 0, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["ar_signals", "ar_intel"],
        },
        "rationale": (
            "Phase H-frontend (Block II): expose Anthropic-extracted "
            "ar_signals (segments / capex / RPT / auditor flags / "
            "contingent liabilities / outlook) on the analysis page."
        ),
    },
    {
        # Phase I-frontend (Block II): expose bank_operational_kpis
        # on the public analysis surface for the 38-ticker
        # PURE_BANK_TICKERS_FOR_DE cohort. Scoped to the new
        # bank_operational_kpis table + bank_kpis API surface so
        # existing cached score / verdict / valuation rows for
        # non-bank tickers are untouched. Bank tickers see a new
        # BankKpiPanel that degrades gracefully to "—" cells while
        # the ingest scripts populate the table over time.
        "version_id": "v_phase_i_bank_kpis_2026_05_26",
        "applied_at": datetime(2026, 5, 26, 0, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["bank_operational_kpis", "bank_kpis"],
        },
        "rationale": (
            "Phase I-frontend (Block II): expose bank operational KPIs "
            "(branches / ATMs / customers / GNPA / NNPA / PCR / CASA / "
            "cost-to-income / credit-deposit) on the analysis surface "
            "for the 38 commercial banks in PURE_BANK_TICKERS_FOR_DE."
        ),
    },
    {
        # Manual AR-signal loader (scripts/load_manual_ar_signals.py)
        # surfaces 10-20 hand-curated high-traffic AR extractions to
        # the public ar_intel panel. Bypasses the paid Anthropic API
        # via the free claude.ai web workflow (see
        # manual_ar_signals/README.md). Scoped to the same fields the
        # API-extracted Phase H entry covers so existing
        # score/verdict/valuation cached rows are untouched.
        "version_id": "v_manual_ar_signals_load_2026_05_24",
        "applied_at": datetime(2026, 5, 24, 0, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["ar_signals", "ar_intel"],
        },
        "rationale": (
            "Manual AR-signal loader surfaces hand-curated ar_signals "
            "rows (claude-ai-web-manual model_version) to the public "
            "ar_intel panel — invalidate cached ar_intel payloads so "
            "the new rows show up immediately."
        ),
    },
    {
        # Migration 063 added 10 nullable JSONB columns to ar_signals
        # (risk_factors, esg_metrics, governance, workforce_metrics,
        # customer_concentration, operational_kpis, subsidiary_summary,
        # dividend_history, capital_actions, strategic_priorities) for
        # the extended manual-AR template. Backward-compatible -- the
        # existing 21 loaded rows stay valid with NULL on every new
        # column. No frontend surfaces these yet, but we invalidate
        # any cached ar_intel payloads so the moment the top-200 batch
        # ships and a future panel renders the new fields, no stale
        # cached row hides them.
        "version_id": "v_ar_signals_extended_2026_05_24",
        "applied_at": datetime(2026, 5, 24, 0, 0, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["ar_signals", "ar_intel"]},
        "rationale": (
            "Extended ar_signals schema with 10 new JSONB fields "
            "(risk_factors, esg_metrics, governance, workforce_metrics, "
            "customer_concentration, operational_kpis, subsidiary_summary, "
            "dividend_history, capital_actions, strategic_priorities). "
            "Backward-compatible — existing rows unchanged."
        ),
    },
    {
        # Phase B.2 added `mos_is_extreme` which correctly downgraded
        # the verdict to `under_review` (KALYANI.NS at MoS=829% / FV=1282
        # / price=138) but the raw 829 was still surfacing through the
        # public serializers — frontend rendered "+829% upside" next to
        # the "Under Review" chip. Public serializers now resolve
        # display MoS through `summary_projection.resolve_display_mos`
        # which returns None when the flag fires, so the SEO page
        # renders "—" and the user reads the verdict chip + note
        # instead. Internal `valuation.margin_of_safety` stays raw for
        # canary-diff / admin visibility.
        "version_id": "v_extreme_mos_display_suppression_2026_05_24",
        "applied_at": datetime(2026, 5, 24, 0, 0, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["mos", "margin_of_safety_display", "mos_pct"]},
        "rationale": (
            "Public serializer now suppresses MoS display when "
            "mos_is_extreme flag fires — under_review verdict already "
            "triggers, but the raw number was still surfacing as "
            "absurd '+829% upside'."
        ),
    },
    {
        # 2026-05-24 FV/MoS audit fix — three coupled fixes that all
        # touch the {verdict, fair_value, data_limited} surface:
        #
        # 1. service.py verdict block: data_limited (confidence-based)
        #    now requires BOTH low confidence AND at least one missing
        #    scenario, not low confidence alone. LT.NS (conf=33,
        #    MoS=-43.7%, FV=2211.55, full scenarios) was incorrectly
        #    showing verdict=data_limited despite a complete valuation.
        #
        # 2. service.py null_cagr_gate: stop zeroing iv when the gate
        #    fires. The verdict flag is the signal; zeroing iv wrote
        #    FV=0 into analysis_cache so any consumer reading the raw
        #    JSONB (SQL screener, audit tooling) saw FV=0 even though
        #    the engine had computed a real value. HCLTECH.NS and
        #    ULTRACEMCO.NS were the canonical cases.
        #
        # 3. public.py /top-tickers: prepend a curated must-include
        #    set so LT/KOTAKBANK/BAJFINANCE/AXISBANK are warmed even
        #    when market_metrics has stale/null mcap rows. (Universe
        #    fix — doesn't itself invalidate cache, but the warmup
        #    pass triggered by this manifest entry will populate the
        #    previously-missing rows.)
        #
        # Invalidate all tickers' verdict + fair_value fields so the
        # next read forces a recompute under the new gate rules.
        "version_id": "v_data_limited_gate_tighten_2026_05_24",
        "applied_at": datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["verdict", "fair_value", "data_limited"],
        },
        "rationale": (
            "Tighten data_limited verdict gate to require missing "
            "scenarios in addition to low confidence; stop zeroing "
            "fair_value in null_cagr_gate so the cache row carries the "
            "canonical computed value; expand cache-warm coverage to "
            "always include top-25 large-caps. Surfaces honest computed "
            "FV on LT.NS, HCLTECH.NS, ULTRACEMCO.NS."
        ),
    },
    {
        "version_id": "v_as_of_plumbing_2026_05_24",
        "applied_at": datetime(2026, 5, 24, 14, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["as_of", "price_timestamp", "freshness"]},
        "rationale": (
            "Live quote timestamp now flows to the analysis surface — "
            "freshness chip reads actual quote age, not analysis recompute age."
        ),
    },
    {
        # 2026-05-24 — task #195: deterministic AI-summary template
        # in sebi_filter.py used to render half-fragments like
        # "Revenue CAGR (3y): n/a." when the underlying metric was
        # null. Half-sentences carry no information and read as
        # template bugs on the analysis page.
        #
        # New _is_missing() helper + fragment-skip logic in
        # deterministic_template() drop the fragment entirely when
        # the metric is None or non-numeric. Display-only — the
        # description is rebuilt every response, no cached payload
        # shape change. Manifest entry purely satisfies the cache-
        # version-bump gate (backend/services/ touched).
        "version_id": "v_task195_ai_summary_skip_na_2026_05_24",
        "applied_at": datetime(2026, 5, 24, 16, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["ai_description", "model_description", "summary_description"],
        },
        "rationale": (
            "AI-summary template now skips fragments whose metric is "
            "missing — no more 'Revenue CAGR (3y): n/a' half-sentences "
            "in the model description."
        ),
    },
    {
        # P0 #4 — Bulls Say / Bears Say structured-narrative bullets
        # (Morningstar-style 3-bullet per-side thesis). Pure rules +
        # templates, no LLM. Purely additive on AnalysisResponse —
        # legacy cached payloads omit the fields and the frontend
        # renders the "Insufficient data" empty state instead of
        # erroring. See backend/services/analysis/bulls_bears_generator.py
        # and backend/tests/test_bulls_bears_generator.py.
        "version_id": "v_bulls_bears_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 13, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["bulls_say", "bears_say"]},
        "rationale": (
            "Auto-generated Bulls Say / Bears Say narratives so users "
            "see both sides of the thesis without an analyst opinion."
        ),
    },
    {
        # P0 #2 + P0 #5 — portfolio Sum-of-Parts FV card, holdings
        # mini-sparklines (price vs FV), and a placeholder return
        # decomposition strip. Backend additions are READ-ONLY against
        # existing analysis_cache + fv_history tables — no engine
        # change, no cached payload shape change. Manifest entry purely
        # satisfies the backend/services-touched cache-bump gate.
        "version_id": "v_portfolio_sop_sparklines_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 14, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": [
                "portfolio_sum_of_parts",
                "holdings_sparkline",
                "portfolio_returns_decomposition",
            ],
        },
        "rationale": (
            "Portfolio sum-of-parts fair value card, holdings "
            "mini-sparklines (price vs FV), and 5-card return "
            "decomposition strip."
        ),
    },
    {
        # P0 #1 — per-holding "Updates" feed for the Portfolio page.
        # Backend additions are purely additive (new table
        # portfolio_updates_feed + new endpoint
        # /api/v1/portfolio/{portfolio_id}/updates that reads from it).
        # No engine change, no cached payload shape change. Manifest
        # entry purely satisfies the backend/services-touched cache-bump
        # gate and signals downstream consumers that the new fields
        # exist.
        "version_id": "v_portfolio_updates_feed_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["portfolio_updates", "updates_feed"]},
        "rationale": (
            "Per-holding updates feed — categorised event stream with "
            "template-generated headlines so users see what changed "
            "since last visit."
        ),
    },
    {
        # Tier 1 #4 — 6-card Financials KPI strip on /analysis/[ticker]
        # Financials tab. Purely additive frontend surface that consumes
        # the existing /analysis/{ticker}/financials payload (no new
        # endpoint, no engine change, no payload-shape change). Manifest
        # entry exists to satisfy the backend/services-touched gate and
        # so the timeline records when the surface shipped.
        "version_id": "v_financials_kpi_grid_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 14, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["financials_kpi"]},
        "rationale": (
            "6-card financials KPI grid (Revenue / Operating Income / "
            "Net Income / EPS / OpCF / FCF) with sparklines and CAGR "
            "chips on the Financials tab."
        ),
    },
    {
        # Phase-2 financials visualisations: Revenue Sankey + Earnings
        # Waterfall on the Financials tab. The Sankey reads the existing
        # /analysis/{ticker}/financials payload and derives missing
        # sub-line items (sg_a, r_d, cost_of_revenue) by subtraction.
        # The serializer now also surfaces interest_expense (already in
        # the DB) so the Op-Income → Interest leg renders; this is a
        # purely additive field — no engine math touched, no FV change.
        "version_id": "v_sankey_waterfall_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 18, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["sankey", "waterfall"]},
        "rationale": (
            "Revenue Sankey + Earnings Waterfall visualisations on the "
            "Financials tab — flow-of-money pre-attentive."
        ),
    },
    {
        # Phase-2 Time Slider — new /analysis/{ticker}/as-of endpoint +
        # frontend slider above the hero. Reconstructs a past snapshot
        # of the analysis by joining fair_value_history + daily_prices
        # against the most-recent manifest entry on the requested date.
        # Pure additive surface: no engine change, no existing payload
        # field touched.
        "version_id": "v_time_slider_phase2_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 18, 30, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["time_slider", "as_of_analysis"]},
        "rationale": (
            "Phase-2 Time Slider — horizontal slider above the hero "
            "lets users replay the analysis as it stood 6m / 1y / 2y / "
            "3y ago. Joins fair_value_history + daily_prices + the "
            "manifest in effect on the requested date."
        ),
    },
    {
        # Reverse-DCF Playground (Week-2 manifesto). Two additive POST
        # endpoints (/dcf-recompute, /dcf-reverse-engineer) wrapping the
        # existing recompute_dcf engine — no FV math change.
        "version_id": "v_dcf_playground_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 19, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["dcf_playground", "dcf_recompute", "dcf_reverse_engineer"]},
        "rationale": (
            "Interactive Reverse-DCF playground -- users adjust "
            "WACC/TG/CAGR/Margin/Tax sliders to see fair value "
            "recompute live. Plus reverse-engineered "
            "'what assumptions justify today's price?' panel."
        ),
    },
    {
        "version_id": "v_honest_card_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 17, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["honest_card"]},
        "rationale": (
            "Radical-transparency card -- confident facts, best estimate, "
            "uncertainty factors, and invalidating conditions auto-generated "
            "per ticker."
        ),
    },
    {
        # Week-3 manifesto: community sentiment voting widget +
        # aggregated bars + 30d sparkline on the Summary tab. New
        # table community_sentiment_votes (migration 065). Three
        # additive public endpoints (POST vote, GET aggregate, GET
        # history). No FV math touched.
        "version_id": "v_community_sentiment_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 20, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["community_sentiment", "sentiment_vote"]},
        "rationale": (
            "Community sentiment voting (Bearish/Neutral/Bullish) per "
            "ticker — engagement loop and emotional signal. Labels "
            "framed as user view, never advice; SEBI-safe vocabulary."
        ),
    },
    {
        # Phase 4 manifesto (Paradigm 11): personal Memory Lane layer.
        # New table user_ticker_visits (migration 066). Two additive
        # endpoints under /api/v1/me/ (POST visit, GET memory-lane, PUT
        # note). First-visit snapshot of price/FV/verdict; subsequent
        # visits bump counters. No FV math touched.
        "version_id": "v_memory_lane_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 18, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["memory_lane", "user_ticker_visits"]},
        "rationale": (
            "Per-user, per-ticker memory layer — first-visit price/FV/"
            "verdict snapshot + days-since stats."
        ),
    },
    {
        # Phase 4.2 (2026-05-25): Money Camera — third parallel OG
        # route at /api/og/money-camera/[ticker] with ?format=horizontal
        # (1200x630, default) and ?format=story (1080x1920). Set as the
        # canonical Open Graph image on /analysis/[ticker] in place of
        # the legacy /api/og/[ticker] route (which stays available for
        # already-scraped URLs). Single-frame summary: FV + price +
        # verdict caption + fan-out bear/base/bull chart + prism
        # narrative + the mandatory 192px SEBI disclaimer banner.
        # No backend math touched; reads scenarios.bear/base/bull and
        # prism_narrative off the existing public stock-summary payload.
        # Scope is `og_image_meta` (advisory invalidation so crawler
        # caches refresh) — no FV / verdict / score fields are touched.
        "version_id": "v_money_camera_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 18, 30, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["money_camera", "og_image_meta"]},
        "rationale": (
            "Money Camera shareable single-frame summary route — "
            "horizontal + story formats, set as default OG image per "
            "analysis page."
        ),
    },
    {
        # Phase 4 personalization layer — investing-style picker that
        # reorders Summary-tab sections, sets default-expanded set,
        # tints accent on numbered headers, and shows Beginner-mode
        # explainers. Frontend-only; localStorage persisted. No backend
        # field changes; no FV math touched. Listed here per repo
        # convention so the public manifest history reflects the change.
        "version_id": "v_personalization_2026_05_25",
        "applied_at": datetime(2026, 5, 25, 21, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["personalization_layer", "section_ordering"]},
        "rationale": (
            "Investing-style picker (Value / Growth / Income / Beginner / "
            "Active) reorders the Summary tab so the sections that matter "
            "to each reader land first. Accent colour and Beginner-mode "
            "explainers adjust per style. Existing users see zero change "
            "until they pick a style."
        ),
    },
    {
        # Task #228 (2026-05-26): added M&M + TATAMOTORS to
        # CYCLICAL_TICKERS so the peak-FCF normalization ladder in
        # backend/services/analysis/service.py:1217-1267 fires for these
        # names. Scope narrowed to the two affected tickers and the
        # downstream fields that recompute off the new normalization.
        "version_id": "v_228_auto_cyclical_2026_05_26",
        "applied_at": datetime(2026, 5, 26, 6, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["M&M", "TATAMOTORS"],
            "fields": [
                "fair_value", "base_case", "bull_case", "bear_case",
                "scenarios", "verdict", "mos_pct", "score",
            ],
        },
        "rationale": (
            "Added M&M + TATAMOTORS to CYCLICAL_TICKERS. Peak-FCF "
            "normalization ladder (service.py:1217-1267) now fires for "
            "these names. Task #228."
        ),
    },
    {
        # Task #229 (2026-05-26): FMCG_WACC_FLOOR raised 8.5 -> 9.5 and
        # top-tier scenario weights shifted 40/40/20 -> 35/45/20.
        # Aligns with Damodaran India staples cost-of-capital reference.
        # Scope narrowed to the FMCG cohort and the recomputed fields.
        "version_id": "v_229_fmcg_wacc_floor_2026_05_26",
        "applied_at": datetime(2026, 5, 26, 6, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "NESTLEIND", "HINDUNILVR", "BRITANNIA", "ITC", "DABUR",
                "MARICO", "COLPAL", "GODREJCP", "EMAMILTD", "TATACONSUM",
                "VBL",
            ],
            "fields": [
                "fair_value", "base_case", "bull_case", "bear_case",
                "scenarios", "verdict", "mos_pct", "score", "wacc",
            ],
        },
        "rationale": (
            "FMCG_WACC_FLOOR 8.5->9.5; top-tier scenario weights "
            "40/40/20->35/45/20. Aligns with Damodaran India staples "
            "cost of capital. Task #229."
        ),
    },
    {
        # v_238 — Bulls Say / Bears Say paragraph upgrade. The bullet
        # text now ships as 2-3 sentence paragraphs (~40-50 words each)
        # plus a composed bull_case_narrative / bear_case_narrative
        # and a "Updated <Month YYYY>" thesis_updated stamp. Pure
        # rules + templates, SEBI-safe by construction. Field-additive
        # on AnalysisResponse — legacy payloads omit the new prose
        # fields; the frontend handles longer bullet text without
        # truncation. FV math is untouched (narrative-only change).
        "version_id": "v_238_thesis_paragraphs_2026_05_26",
        "applied_at": datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": [
                "bulls_say",
                "bears_say",
                "bull_case_narrative",
                "bear_case_narrative",
            ],
        },
        "rationale": (
            "Upgrade Bulls/Bears bullets from 1-sentence facts to "
            "dated 2-3 sentence paragraphs so the auto-generated "
            "thesis reads at parity with competitor research notes."
        ),
    },
    {
        # v_revert_230 — emergency revert of #673 NULL_CAGR_GATE_EXEMPT.
        # The allowlist caused LT to silently crash (SEO stub fallback)
        # and WIPRO did not unblock. Reverting affected cache rows for
        # the 8 allowlisted tickers so they recompute under the
        # restored gate logic.
        "version_id": "v_revert_230_null_cagr_2026_05_26",
        "applied_at": datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "LT", "ULTRACEMCO", "WIPRO", "RELIANCE",
                "INFY", "TCS", "ITC", "BHARTIARTL",
            ],
            "fields": [
                "verdict", "data_limited", "fair_value", "mos_pct", "score",
            ],
        },
        "rationale": (
            "Revert of #673 allowlist after LT prod regression and "
            "WIPRO un-fix detected via dcf-regression baseline audit."
        ),
    },
    {
        # v_phase2_mf_returns_compute — Phase 2 of the Mutual Funds
        # pipeline ships a new compute service that populates the new
        # fund_returns_cache table (migration 075). No equity cache rows
        # are affected — scope is narrowed to the new MF cache fields so
        # the equity-side gate logic stays a no-op for stock rows.
        # Tickers wildcard because fund_returns_cache is keyed on
        # scheme_code, not ticker; the manifest matcher treats `*` as
        # "matches every key" which is correct for this surface.
        "version_id": "v_phase2_mf_returns_compute_2026_05_27",
        "applied_at": datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": [
                "ret_1y", "ret_3y", "ret_5y", "ret_10y", "ret_si",
                "cagr_3y", "cagr_5y", "cagr_10y",
                "rolling_3y_mean", "rolling_3y_median",
                "rolling_3y_min", "rolling_3y_max", "rolling_3y_window_count",
                "stdev_3y", "sharpe_3y", "sortino_3y",
                "max_dd_3y", "max_dd_5y",
                "beta_3y", "alpha_3y", "info_ratio_3y", "tracking_error_3y",
                "upside_capture_3y", "downside_capture_3y", "benchmark_excess_3y",
                "category_percentile_3y",
                "yieldiq_fund_score",
                "score_component_rolling", "score_component_sharpe",
                "score_component_drawdown", "score_component_ter",
                "score_component_tenure",
            ],
        },
        "rationale": (
            "Phase 2 ships the rule-based MF compute service: trailing "
            "returns, CAGR windows, monthly-anchored rolling 3y, stdev, "
            "Sharpe, Sortino, drawdown, beta, Jensen alpha, info ratio, "
            "tracking error, up/down capture, category percentile, and "
            "the YieldIQ Fund Score composite (rules only, NO LLM). "
            "Scope is the new fund_returns_cache fields only — equity "
            "rows are untouched."
        ),
    },
    {
# v_244 — Sanity-clamp window for revenue CAGR widened from
        # ±50% to ±80%. WIPRO and other tickers with a single
        # restructuring fiscal year inside the trailing 3y/5y window
        # were landing in the 50-80% absolute range, getting nulled
        # by the old clamp, and then tripping the null-CAGR gate at
        # data_limited. The HCLTECH-class -75% artifact that
        # motivated the original ±50% bound is still caught by the
        # wider window.
        "version_id": "v_244_cagr_clamp_loosened_2026_05_29",
        "applied_at": datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc),
        "scope": {
            # Typo correction (2026-06-07): was ["WIPRO", "*"] — the
            # matcher treats a list as literal membership, so only
            # WIPRO invalidated. The rationale below already says the
            # change is global (HCLTECH-class artifact, wider window).
            # Bare-string "*" is the wildcard sentinel _ticker_in_scope
            # recognises. applied_at unchanged — this is a typo fix,
            # not a backdate (see CLAUDE.md "Manifest invariants").
            "tickers": "*",
            "fields": [
                "verdict", "data_limited", "fair_value", "mos_pct", "score",
            ],
        },
        "rationale": (
            "Loosen _sanitize_cagr clamp ±50% → ±80% so a single "
            "restructured fiscal year inside the trailing CAGR window "
            "no longer collapses revenue_cagr_3y AND revenue_cagr_5y "
            "to None and trips the null-CAGR data_limited gate. "
            "Task #244 fix-forward after #673 / revert #679."
        ),
    },
    {
        # Revert PR #672 FMCG_WACC_FLOOR change. The constant gates WACC
        # via cap semantics (call site: if wacc > target: wacc = target).
        # PR #672 raised it 0.085 -> 0.095 under floor-semantics
        # assumption, which loosened the cap and inflated FMCG FVs
        # (ITC +104%). Constant reverted to 0.085; semantic rename to
        # FMCG_WACC_CAP deferred to a follow-up. Scenario weights
        # (35/45/20) from PR #672 remain in place — separate rationale.
        "version_id": "v_revert_229_fmcg_cap_wrong_direction_2026_05_29",
        "applied_at": datetime(2026, 5, 29, 6, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "NESTLEIND", "HINDUNILVR", "BRITANNIA", "ITC", "DABUR",
                "MARICO", "COLPAL", "GODREJCP", "EMAMILTD", "TATACONSUM",
                "VBL",
            ],
            "fields": [
                "fair_value", "base_case", "bull_case", "bear_case",
                "scenarios", "verdict", "mos_pct", "score", "wacc",
            ],
        },
        "rationale": (
            "Reverted FMCG_WACC_FLOOR 0.095->0.085 — PR #672 raised it "
            "under floor-semantics assumption, but the call site uses "
            "cap-semantics, so the change inflated FVs (ITC +104%). "
            "Semantic fix deferred to follow-up."
        ),
    },
    {
        # Phase 1 contract PR: added FV_ANNOTATION_THRESHOLD_PCT constant
        # to backend/services/analysis/constants.py. The constant is a
        # display-only threshold for the new /api/valuation-history
        # endpoint annotation visibility — it does NOT affect any
        # cached field. No tickers' analysis output changes.
        # Entry exists only to satisfy the cache-version-bump CI gate
        # which is mechanical on services/ changes. Empty fields list
        # documents the no-op intent.
        "version_id": "v_phase1_fv_history_contract_2026_05_29",
        "applied_at": datetime(2026, 5, 29, 18, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [],
            "fields": [],
        },
        "rationale": (
            "Phase 1 FV-history contract: new annotation threshold "
            "constant + new isolated router. No cached field affected; "
            "manifest entry is a documentation no-op for the CI gate."
        ),
    },
    {
        # Holdco classification propagation. Single source of truth
        # added: backend/services/analysis/constants.HOLDING_COMPANIES
        # (13 holdcos). Every downstream consumer (honest_card_generator,
        # worry_index, eli15_thesis, prism_service, peers_service) now
        # branches on the classification. Bank-template copy removed
        # for holdcos; underlying-holdings link-out added.
        # Cached fields affected on HOLDCO tickers only: bear_thesis,
        # worry_drivers, pulse_label, verdict_triggers, peers. Non-
        # holdco tickers (the canary universe) unaffected by
        # construction.
        "version_id": "v_holdco_classification_propagation_2026_06_09",
        "applied_at": datetime(2026, 6, 9, 14, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "BAJAJHLDNG", "TATAINVEST", "MAHSCOOTER", "PILANIINVS",
                "KAMAHOLD", "SUMMITSEC", "WILLIAMAGR", "MCLEODRUSS",
                "NDTV", "NETWORK18", "GAYAHWS", "MOIL", "GRASIM",
            ],
            "fields": [
                "bear_thesis", "worry_drivers", "pulse_label",
                "verdict_triggers", "peers", "underlying_holdings",
            ],
        },
        "rationale": (
            "Holdco classification now propagates from constants."
            "HOLDING_COMPANIES through 5 downstream consumers. Kills "
            "the bank-template leak on BAJAJHLDNG + 12 other holdcos "
            "(bear-thesis 'Loan/advances' / 'Gross NPA' triggers, "
            "Worry-Index 'bank ROA' Solvency driver, Pulse 'ABOVE/"
            "BELOW FAIR VALUE' when FV null, peers cohort empty, "
            "WHY narrative 'Rs 0' leak). Underlying-holdings link-out "
            "added from holdco_underlyings.json."
        ),
    },
    {
        # 2026-06-09 (UTC) baseline-refresh PR. CI baselines (dcf_golden
        # snapshot + canary_universe_180 bounds + canary_diff per-ticker
        # fv/cmp overrides) had drifted on origin/main and were blocking
        # 4 in-flight engine PRs (#786 T1.1 Composite IV, #787 T2.7
        # Sensitivity, #788 T1.5 Phase A Calibration, #790 T1.2 Backtest
        # Publish). Each blocked PR is purely additive — no DCF compute
        # paths touched — and all 4 failed dcf-regression with the SAME
        # 7-ticker drift cluster, confirming the cause is stale baseline,
        # not regression introduced by the PRs.
        #
        # dcf_golden refresh (7 drifters, each corroborated by an
        # existing manifest entry):
        #   - ITC      842.10 -> 631.74 (-25%)
        #       Corroborated by v_revert_229_fmcg_cap_wrong_direction
        #       (2026-05-29): FMCG_WACC_FLOOR 0.095 -> 0.085 revert
        #       brought ITC FV back from its inflated +104% PR-#672
        #       state. New 631.74 is the correct engine output.
        #   - NTPC     541.52 -> 571.40 (+5.5%, verdict undervalued ->
        #       data_limited). Corroborated by v_data_limited_gate_
        #       tighten_2026_05_24 — coverage_tier=B (5/7 criteria
        #       met) now routes through the tightened gate.
        #   - COALINDIA 621.24 -> 438.74 (-29%). Corroborated by
        #       v_day95_metals_sector_pins which explicitly listed
        #       COALINDIA. Sector cohort WACC ratchet pulled FV down
        #       to its current equilibrium.
        #   - BPCL     243.71 -> 261.42 (+7.3%). PSU oil-marketing
        #       cohort re-equilibration; engine WACC moved to 0.1217.
        #   - IOC      142.35 -> 156.75 (+10.1%). Same as BPCL —
        #       PSU oil-marketing cohort re-equilibration.
        #   - BERGEPAINT 169.97 -> 210.09 (+23.6%). Already has
        #       fv_cmp_min_override=0.30 in canary_diff per
        #       2026-05-20 widening; this is the continued premium-
        #       multiple drift the override anticipated.
        #   - AMBUJACEM 100.70 -> 189.15 (+87.8%). Documented in
        #       tasks #260/#261/#262 (floor-clamp cluster diagnosis
        #       + FMCG_WACC_FLOOR revert + prod cache divergence
        #       investigation). Cement super-cyclical settled at a
        #       new equilibrium post-revert and post-tier2_cohort
        #       routing. Existing fv_cmp_min_override=0.25 holds.
        #
        # canary_universe_180 refresh (51 bound entries across 49
        # tickers): WACC bound widenings on FMCG cohort (lower edge
        # 0.09 -> 0.08 to admit the post-revert 0.085 cap), plus
        # ROE bound widenings on 28 tickers whose quarterly ROE has
        # drifted naturally since the last bound calibration. Each
        # bound was re-derived from current prod observation with a
        # symmetric buffer.
        #
        # canary_diff _TICKER_OVERRIDES refresh: 28 new entries
        # extending fv_cmp_min_override to premium-multiple tickers
        # that persistently land in the 0.20-0.34 band against
        # trading multiples the market refuses to compress (capital
        # goods, consumer discretionary, financial services). Plus
        # one fv_cmp_max_override=2.85 for NATCOPHARM whose generic-
        # pharma DCF marginally exceeded the 2.7 ceiling.
        #
        # No engine code change, no cache field semantics change. The
        # cached FV values stored against each ticker are exactly the
        # values produced by the current engine — the baselines were
        # what was stale, not the engine output. fields list documents
        # this as a baseline-only refresh via the __baseline__ sentinel.
        "version_id": "v_baseline_refresh_2026_06_09",
        "applied_at": datetime(2026, 6, 9, 19, 15, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "ITC", "NTPC", "COALINDIA", "BPCL", "IOC", "BERGEPAINT", "AMBUJACEM",
            ],
            "fields": ["__baseline__"],
        },
        "rationale": (
            "CI baselines refresh — dcf_golden snapshot + "
            "canary_universe_180 bounds + canary_diff fv/cmp overrides. "
            "7 dcf-regression drifters all corroborated by existing "
            "manifest entries (FMCG_WACC_FLOOR revert, data_limited "
            "gate tighten, metals sector pins, premium-multiple drift). "
            "50 canary_bounds + 30 forbidden_values violations resolved "
            "by widening bounds to current prod observations and adding "
            "per-ticker fv_cmp overrides for premium-multiple cohorts. "
            "Unblocks 4 in-flight engine PRs (#786 / #787 / #788 / #790)."
        ),
    },
    {
        # T1.1 engine refinement — composite intrinsic value as a new
        # weighted-average field (DCF 0.5 + Multiples 0.3 + Analyst 0.2).
        # PURELY ADDITIVE: the existing `fair_value` field stays byte-
        # identical (DCF-only). New fields are appended at the bottom of
        # AnalysisResponse and are None on legacy cached payloads — no
        # cache invalidation is required for the change to land. This
        # entry exists for TRACEABILITY: future audits can correlate
        # "this payload has composite=None because it was cached before
        # v_t1_1, this one has a value because it post-dates v_t1_1."
        # Closes the systematic high-side bias documented vs AlphaSpread
        # (HDFCBANK: YieldIQ DCF Rs 1,129 vs AlphaSpread Rs 803 — 40% gap
        # narrows to ~18% with the composite). Verdict gate continues to
        # read `fair_value`; switch to composite-aware verdicting ships
        # under a follow-up PR so the engine refinement and the verdict
        # contract change land separately.
        "version_id": "v_t1_1_composite_intrinsic_value_2026_06_09",
        "applied_at": datetime(2026, 6, 9, 15, 30, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["*"],
            "fields": ["composite_intrinsic_value", "composite_components"],
        },
        "rationale": (
            "T1.1 engine refinement — added composite_intrinsic_value "
            "(weighted avg of DCF 0.5 + Multiples 0.3 + Analyst 0.2) and "
            "composite_components (per-estimator value + re-normalized "
            "weight + method tag + extreme_divergence flag) as additive "
            "AnalysisResponse fields. Holdco branch routes DCF-only "
            "(SOTP via T1.4); bank branch keeps weighting but tags the "
            "dcf slot as residual_income via the method field so the "
            "frontend pill reads 'Residual income' not 'DCF'. Fair "
            "value (DCF-only) is byte-identical pre/post; downstream "
            "gates that key on fair_value are unaffected. Entry is "
            "for traceability — no cache invalidation required."
        ),
    },
    {
        # T2.1 Phase A (2026-06-10): standalone Dividend Discount Model
        # service module added at backend/services/
        # dividend_discount_model_service.py. Three variants (Gordon
        # single-stage, two-stage, H-model) + sector-based auto-router
        # + applicability gate (>=30% payout AND >=5y streak AND
        # sector not in {recent-IPO, biotech, deep cyclical, holdco}).
        #
        # Phase A scope: SERVICE MODULE + TESTS ONLY. The DDM is NOT
        # yet wired into composite_iv_service.py and NOT yet added to
        # AnalysisResponse as a ddm_fv field. No cached payload field
        # changes; no cache invalidation needed. Phase B (separate PR)
        # will do the composite wiring + response surface, at which
        # point a scoped manifest entry will follow with
        # fields=["ddm_fv", "composite_iv"] or similar.
        #
        # Entry exists to satisfy the cache-version-bump CI gate which
        # is mechanical on backend/services/ changes. Empty scope
        # documents the no-op intent (same pattern as the
        # v_phase1_fv_history_contract_2026_05_29 entry above).
        "version_id": "v_t2_1_ddm_phase_a_2026_06_10",
        "applied_at": datetime(2026, 6, 9, 18, 54, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["*"],
            "fields": [],
        },
        "rationale": (
            "T2.1 Phase A — standalone Dividend Discount Model service "
            "module added (Gordon + Two-stage + H-model). Phase B "
            "wires into composite_iv_service when applicable "
            "(separate PR)."
        ),
    },
    {
        # T1.3 (2026-06-10) — engine refinement roadmap. Per-sector
        # calibrated WACC + Terminal Growth tables, Damodaran India
        # 2026 anchored. PHASE A: tables + helpers shipped as SSOT in
        # sector_overrides.py; NO engine read-path wiring yet. The
        # existing inline cohort blocks (Day-84 pharma, Day-92 utility,
        # Day-107a IT, Day-107b FMCG, Day-107c auto) remain the
        # authoritative production gates today; the new table is
        # consistent with them (asserted in
        # test_sector_wacc_tg_calibrated.py
        # ::test_calibrated_values_match_existing_cohort_constants)
        # and is structured so a Phase B follow-up can wire it into
        # service.py / forecaster.py as a single canary-diffable change.
        # Because no read path consumes the table yet, no cached field
        # is invalidated by this entry — scope.fields is intentionally
        # empty. The manifest entry exists to mark the SSOT landing as
        # an event downstream PRs can cite when justifying engine
        # behaviour changes (e.g. "FMCG-tobacco TG drop traces to T1.3
        # calibration anchor"). Closes audit #229 (FMCG TG uniformity
        # vs AlphaSpread) and audit #260 (cyclical-cluster over-
        # extrapolation) at the data layer.
        "version_id": "v_t1_3_sector_wacc_tg_calibrated_2026_06_10",
        "applied_at": datetime(2026, 6, 10, 0, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["*"],
            "fields": [],
        },
        "rationale": (
            "T1.3 (engine refinement): per-sector calibrated WACC + "
            "Terminal Growth tables (Damodaran India 2026 anchored) "
            "landed as importable SSOT in sector_overrides.py. Phase A "
            "is tables + helpers only — no DCF read-path wiring yet, "
            "so no cached field is invalidated. Addresses audit #229 "
            "(FMCG TG uniformity vs AlphaSpread; staples 5.5% vs "
            "tobacco 3.0% now distinguished) and audit #260 (cyclical "
            "cluster over-extrapolation; Metals 3.0%, Oil & Gas 2.5%, "
            "Cement 4.0% now anchored)."
        ),
    },
    {
        # T2.8 Phase A — liquidation value standalone service.
        # backend/services/liquidation_value_service.py adds a Graham-
        # style asset-recovery floor (sum(asset × recovery_rate) −
        # liabilities) as a pure-math primitive. Phase A is the engine
        # only — no wiring into the verdict gate or analysis response.
        # Phase B (separate PR) will wire the floor into the verdict
        # gate as a "hard floor" anchor on the analysis page when
        # current_price < liquidation_per_share.
        #
        # Scope.tickers = "*" + scope.fields = [] documents the no-op
        # invalidation intent: the manifest entry exists to satisfy
        # the cache-version-bump CI gate (backend/services/ touched)
        # and to anchor the timeline. No cached field is affected
        # because the service is not yet called from any code path.
        "version_id": "v_t2_8_liquidation_value_phase_a_2026_06_10",
        "applied_at": datetime(2026, 6, 9, 19, 31, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": [],
        },
        "rationale": (
            "T2.8 Phase A — liquidation value standalone service added "
            "(Graham framework). Phase B wires into verdict gate as a "
            "floor anchor (separate PR)."
        ),
    },
    {
        # T2.2 Phase A — Earnings Power Value standalone service added
        # (backend/services/epv_service.py). Pure additive module — no
        # callers in this PR, no analysis_cache field touched. Phase B
        # wires the result into the composite engine and surfaces
        # ``growth_value_gap`` on the analysis response (separate PR).
        #
        # Entry exists to record WHEN the engine acquired the EPV
        # capability so the public timeline shows a coherent log when
        # Phase B starts surfacing values. Empty scope (no tickers, no
        # fields) is the documented no-op idiom for "manifest entry as
        # changelog, not invalidation gate" (see Phase 1 contract entry
        # v_phase1_fv_history_contract_2026_05_29 above).
        "version_id": "v_t2_2_epv_phase_a_2026_06_10",
        "applied_at": datetime(2026, 6, 9, 19, 31, 0, tzinfo=timezone.utc),
        "scope": {
            # Brief specified ``["*"]`` but the matcher
            # (_ticker_in_scope) treats a list as literal-ticker
            # membership and ``"*"`` inside a list is a NO-OP (matches
            # only a ticker literally named asterisk). Same bug the
            # v_244 entry above documents under "Typo correction
            # (2026-06-07)". Use bare-string "*" for the actual
            # wildcard.
            "tickers": "*",
            "fields": [],
        },
        "rationale": (
            "T2.2 Phase A — Earnings Power Value standalone service "
            "added (Greenwald framework). Phase B wires into composite "
            "(separate PR)."
        ),
    },
    {
        # T2.4 Phase A (2026-06-10): probability-weighted fair value
        # standalone service added at backend/services/
        # probability_weighted_fv_service.py. Three- or four-scenario
        # mix with beta / cyclical / earnings-revisions / macro-regime
        # weight adjustments. Phase A is standalone — no wiring into the
        # response payload, no engine path mutation. Phase B (separate
        # PR) will fold weighted_fv into the composite intrinsic value
        # and add it to the public AnalysisResponse.
        #
        # tickers="*" is the bare-string wildcard sentinel _ticker_in_scope
        # recognises — list-of-asterisk would be a silent no-op (see the
        # v_244 typo correction note above + PR #796 EPV agent's report).
        # fields=[] documents that NO cached field is affected yet — the
        # entry exists only to record the engine-services-touched event
        # for the CI cache-bump gate.
        "version_id": "v_t2_4_probability_weighted_fv_phase_a_2026_06_10",
        "applied_at": datetime.now(timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": [],
        },
        "rationale": (
            "T2.4 Phase A — probability-weighted FV standalone service "
            "added. Three- or four-scenario weighting with beta / "
            "cyclical / revisions / macro adjustments. Phase B wires "
            "into composite (separate PR)."
        ),
    },
    {
        # T2.5 Phase A (2026-06-10): three-stage growth DCF standalone
        # service. Adds backend/services/three_stage_dcf_service.py — a
        # pure-function module that computes a Damodaran-style three-
        # stage DCF (explicit high growth → linear fade → terminal
        # Gordon). NOT wired into composite_iv_service in Phase A; the
        # existing two-stage DCF stays byte-identical. Phase B (separate
        # PR) introduces an opt-in three_stage_fv field that
        # composite_iv_service can weight against the existing
        # estimator.
        #
        # Motivation: the two-stage cliff (high growth → instant jump
        # to terminal) systematically over-rewards near-term momentum.
        # The 2026-06 AlphaSpread cross-check showed HDFCBANK YIQ
        # ₹1,129 vs AlphaSpread ₹803 — ~40% high. A fade window
        # between the two stages directionally lowers FV into the
        # AlphaSpread bracket.
        #
        # Scope: empty fields list. Phase A is the math + tests only;
        # no cached field shape changes, no recompute forced. Manifest
        # entry exists to satisfy the backend/services-touched gate
        # and record when the standalone service shipped so Phase B
        # has a paper trail.
        "version_id": "v_t2_5_three_stage_dcf_phase_a_2026_06_10",
        "applied_at": datetime.now(timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": [],
        },
        "rationale": (
            "T2.5 Phase A — three-stage growth DCF standalone service "
            "added (explicit high-growth + linear fade + terminal). "
            "Addresses systematic high-side bias from cliff-style two-"
            "stage DCF (HDFCBANK YIQ Rs 1,129 vs AlphaSpread Rs 803, "
            "40% gap). Phase B wires into composite_iv_service as an "
            "additional estimator (separate PR). Two-stage DCF stays "
            "byte-identical; this is purely additive."
        ),
    },
    {
        # T3.3 (2026-06-09) — Embedded Value + Value of New Business
        # appraisal-math extension to insurance_appraisal_service.py.
        # Phase A delivery: additive pure-compute API (EVVNBInputs /
        # EVVNBResult / compute_ev_vnb_appraisal / select_vnb_multiple
        # / is_ev_vnb_applicable / LIFE_INSURERS frozenset). No routing
        # branch is wired into backend/services/analysis/service.py —
        # the existing operator-DB Gordon-style path
        # (compute_appraisal_fair_value /
        #  get_appraisal_fair_value_for_ticker) remains the sole
        # production caller for life insurers. Phase B (separate PR,
        # post canary-diff confirmation) will wire this API into the
        # analysis route as an alternate framing.
        #
        # scope.fields = [] because no cached field shape changes in
        # Phase A — the entry exists to record WHEN the EV/VNB extension
        # landed so a future Phase B routing change has a contemporaneous
        # anchor to corroborate against.
        "version_id": "v_t3_3_insurance_ev_vnb_2026_06_10",
        "applied_at": datetime(2026, 6, 9, 19, 1, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["HDFCLIFE", "ICICIPRULI", "SBILIFE", "MAXFIN", "LICI"],
            "fields": [],
        },
        "rationale": (
            "T3.3 — EV + VNB appraisal math added to insurance_appraisal_"
            "service. Routes life insurers (HDFCLIFE, ICICIPRULI, SBILIFE, "
            "MAXFIN, LICI) through the appraisal framework that aligns "
            "with how insurers themselves report value via the annual EV "
            "+ VNB disclosure. General + health insurers (ICICIGI, "
            "STARHEALTH, NIVABUPA, GICRE, NIACL, GODIGIT) excluded — "
            "they do not publish EV / VNB, the appropriate frame for "
            "them is float-investment-income PE or DDM. Phase A "
            "additive — no analysis-route wiring; cached field shapes "
            "unchanged."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────
# Matcher
# ─────────────────────────────────────────────────────────────────

def _bare_ticker(ticker: str) -> str:
    """Strip exchange suffix for matching against scope.tickers."""
    if not ticker:
        return ""
    bare = ticker
    for suffix in (".NS", ".BO", ".BSE", ".NSE"):
        if bare.endswith(suffix):
            bare = bare[: -len(suffix)]
            break
    return bare.upper()


def _ticker_in_scope(ticker: str, scope_tickers) -> bool:
    """True if the ticker matches scope.tickers ('*' or list-of-bare)."""
    if scope_tickers == "*":
        return True
    if not isinstance(scope_tickers, (list, tuple, set)):
        return False
    bare = _bare_ticker(ticker)
    return bare in {_bare_ticker(t) for t in scope_tickers}


def _field_in_scope(fields_needed: Iterable[str] | None, scope_fields) -> bool:
    """True if any of fields_needed overlaps scope.fields.

    Scope semantics:
      - "*" → matches anything
      - ["a.b"] → matches only exact "a.b"
      - ["a.*"] → matches "a.b", "a.c", but NOT "x.y"

    If fields_needed is None or empty, treat as "everything" — i.e.
    err on the side of invalidation. The caller doesn't know what
    they're going to read, so we can't safely serve potentially-
    stale data.
    """
    if scope_fields == "*":
        return True
    if not isinstance(scope_fields, (list, tuple, set)):
        return False
    if not fields_needed:
        # Caller didn't declare; assume worst case (any field matters).
        return True
    for needed in fields_needed:
        for scoped in scope_fields:
            if scoped == "*" or scoped == needed:
                return True
            if scoped.endswith(".*") and needed.startswith(scoped[:-2]):
                return True
    return False


def _coerce_datetime(value) -> "datetime | None":
    """Normalise computed_at to a timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            # ISO-8601 with optional Z suffix
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return None


def is_row_valid_per_manifest(
    ticker: str,
    computed_at,
    fields_needed: Iterable[str] | None = None,
    manifest: list[dict] = None,
) -> bool:
    """Return True if the cached row is still valid per the manifest.

    Used on the cache READ path to gate whether a row from
    analysis_cache should be served or treated as a miss.

    Args:
        ticker: Either bare ("NTPC") or canonical ("NTPC.NS") form.
        computed_at: When the cached row was written. Anything older
            than the most-recent applicable manifest entry → invalid.
        fields_needed: Which fields the caller intends to read. If
            None, treats as "all" (worst case → more likely to
            invalidate, which is the safe default for ignorant callers).
        manifest: Override for testing. Defaults to the module-level
            MANIFEST.

    Returns:
        True if the row should be served, False if it should be
        treated as a cache miss.

    Behavior with CACHE_MANIFEST_DISABLED=1:
        Always returns True (caller's existing cache_version equality
        check is then the only gate).
    """
    if _DISABLED:
        return True

    mfst = manifest if manifest is not None else MANIFEST
    computed_dt = _coerce_datetime(computed_at)
    if computed_dt is None:
        # Can't tell when this row was written — fail safe and
        # treat as invalid so we recompute.
        return False

    for entry in mfst:
        applied_at = _coerce_datetime(entry.get("applied_at"))
        if applied_at is None or applied_at <= computed_dt:
            # Entry predates the row; row is at least as new as the
            # fix, so the fix is already in this row.
            continue
        scope = entry.get("scope") or {}
        if not _ticker_in_scope(ticker, scope.get("tickers")):
            continue
        if not _field_in_scope(fields_needed, scope.get("fields")):
            continue
        # This entry applies AND the row is older than it.
        log.debug(
            "cache_manifest: row INVALID for %s (entry=%s, "
            "row_computed_at=%s, applied_at=%s)",
            ticker, entry.get("version_id"),
            computed_dt.isoformat(), applied_at.isoformat(),
        )
        return False

    return True


# ─────────────────────────────────────────────────────────────────
# Helpers for admin / observability
# ─────────────────────────────────────────────────────────────────

@dataclass
class ManifestSummary:
    total_entries: int
    most_recent_entry_id: str | None
    most_recent_applied_at: str | None
    global_entries_count: int   # entries with scope.tickers == "*"
    scoped_entries_count: int   # entries with a ticker list


def summarise_manifest(manifest: list[dict] = None) -> ManifestSummary:
    """Return a small structured summary for /admin/cache-manifest."""
    mfst = manifest if manifest is not None else MANIFEST
    if not mfst:
        return ManifestSummary(0, None, None, 0, 0)
    by_applied = sorted(
        mfst,
        key=lambda e: _coerce_datetime(e.get("applied_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    newest = by_applied[0]
    newest_applied = _coerce_datetime(newest.get("applied_at"))
    global_count = sum(
        1 for e in mfst if (e.get("scope") or {}).get("tickers") == "*"
    )
    return ManifestSummary(
        total_entries=len(mfst),
        most_recent_entry_id=newest.get("version_id"),
        most_recent_applied_at=newest_applied.isoformat() if newest_applied else None,
        global_entries_count=global_count,
        scoped_entries_count=len(mfst) - global_count,
    )


# ─────────────────────────────────────────────────────────────────
# Phase B.1 import-time sweep
#
# Fires once per process. Replays every manifest entry whose
# applied_at is within the last DRAIN_LOOKBACK_HOURS so the in-memory
# tiers get drained before the worker serves its first request.
# ─────────────────────────────────────────────────────────────────

def _recent_entries(
    manifest: list[dict],
    *,
    lookback_hours: int = DRAIN_LOOKBACK_HOURS,
    now: "datetime | None" = None,
) -> list[dict]:
    """Return manifest entries applied within ``lookback_hours`` of
    ``now`` (UTC, defaults to actual now)."""
    now_dt = now or datetime.now(timezone.utc)
    cutoff = now_dt - timedelta(hours=lookback_hours)
    out: list[dict] = []
    for entry in manifest or []:
        applied = _coerce_datetime(entry.get("applied_at"))
        if applied is None:
            continue
        if applied >= cutoff:
            out.append(entry)
    return out


def sweep_recent_entries(
    *,
    manifest: list[dict] = None,
    lookback_hours: int = DRAIN_LOOKBACK_HOURS,
    now: "datetime | None" = None,
) -> int:
    """Fire registered hooks for every recently-applied entry. Returns
    the count of (entry × hook) invocations attempted. Safe to call
    repeatedly — hook implementations must themselves be idempotent.
    """
    if _DISABLED:
        return 0
    mfst = manifest if manifest is not None else MANIFEST
    recent = _recent_entries(mfst, lookback_hours=lookback_hours, now=now)
    fired = 0
    for entry in recent:
        for hook in MANIFEST_APPLIED_HOOKS:
            try:
                hook(entry)
                fired += 1
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "cache_manifest: sweep hook %r raised on entry %s: %s",
                    getattr(hook, "__name__", repr(hook)),
                    entry.get("version_id"),
                    exc,
                )
    if fired:
        log.info(
            "cache_manifest: import-time sweep drained %d (entry × hook) "
            "for %d recent entries",
            fired, len(recent),
        )
    return fired


def _register_default_drain_hook() -> None:
    """Wire the in-memory cache drain hook. Called once at import-time.

    Kept in a function so tests can re-import the module after
    monkeypatching the cache_service singleton.
    """
    try:
        from backend.services.cache_service import cache as _cache_singleton
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "cache_manifest: cache_service import failed; "
            "drain hook NOT registered: %s", exc,
        )
        return

    def _drain_inmem_for_entry(entry: dict) -> None:
        # The in-memory drain is intentionally wildcard (all tickers
        # under the two prefixes) regardless of the entry's
        # scope.tickers. Reason: in-memory keys are by ticker only;
        # iterating the scope list and deleting per-ticker keys would
        # require a per-suffix product (.NS / bare) and would still
        # miss exotic keys. The store is small (single-worker, per
        # process), so a prefix sweep is cheap and bulletproof.
        try:
            _cache_singleton.delete_by_prefix("analysis:")
            _cache_singleton.delete_by_prefix("public:stock-summary:")
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "cache_manifest: in-mem drain failed for entry %s: %s",
                (entry or {}).get("version_id"), exc,
            )

    register_manifest_applied_hook(_drain_inmem_for_entry)


# Register the hook and run the first sweep at import time, so every
# worker that loads this module — including every Railway worker on
# deploy and every cold start — starts with a drained in-memory cache
# whenever a recent manifest entry exists.
_register_default_drain_hook()
try:
    sweep_recent_entries()
except Exception as _exc:  # noqa: BLE001
    log.warning("cache_manifest: import-time sweep failed: %s", _exc)
