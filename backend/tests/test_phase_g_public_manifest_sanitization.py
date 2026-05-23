"""Task #123 (2026-05-23) — public-surface sanitization of the
cache-invalidation manifest.

Background
----------
Internal engineering cadence tokens — ``Day-107a``, ``Phase B.1``,
``Audit#7``, ``PR #498``, ``Task #123``, bare ``#503`` issue refs —
were leaking onto two anon-facing surfaces:

  1. ``GET /api/v1/public/manifest-history/{ticker}``: returned the
     raw ``version_id`` (e.g. ``v_day107a_it_services_cohort_2026_05_23``)
     and unsanitized ``rationale`` (e.g. ``"Day-107a: IT services
     cohort overrides (WACC tighten, TG lift, scenario re-weight)"``).
  2. ``GET /api/v1/public/sector/{slug}``: returned ``manifest_ref:
     "Day-107a"`` and a ``cohort_notes`` block sprinkled with
     ``"See Day-107a manifest entry"`` style sentences.

End users have no model of our release cadence, and a cadence-keyed
verb like *"Day-107a applied"* reads as advisory — meaningful SEBI
exposure on a non-registered platform.

Contract
--------
* Anon callers of ``/manifest-history`` get:
    - NO ``version_id`` key on entries.
    - NO ``rationale`` key on entries (replaced by ``description``).
    - The ``description`` is the rationale with every internal-cadence
      token stripped (Day-NNN, Phase X, Audit#N, PR#N, Task#N, #NNN).
    - ``applied_at`` and ``fields_affected`` survive unchanged.
* Authed callers get the original raw shape (version_id, rationale).
* ``/sector/{slug}`` drops ``manifest_ref`` entirely and serves a
  sanitized ``cohort_notes`` string.
* The underlying ``MANIFEST`` constant is unchanged — sanitization
  happens at the serializer boundary so authed observability and
  the internal matcher remain bit-identical.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routers import public as public_router  # noqa: E402
from backend.services.cache_invalidation_manifest import (  # noqa: E402
    _public_description,
    _strip_internal_tokens,
    public_manifest_entry,
)


# ─────────────────────────────────────────────────────────────────
# Banned-token regex — kept independent of the helper's own patterns
# so a regression in the helper can't hide a leak from this test.
# ─────────────────────────────────────────────────────────────────
_BANNED = re.compile(
    r"\b(?:Day-\d+[a-z]?|Phase\s+[A-Z](?:\.\d+)?|Audit\s*#\s*\d+|PR\s*#\s*\d+|Task\s*#\s*\d+)\b"
    r"|#\d+\b",
    re.IGNORECASE,
)


def _assert_no_internal_tokens(text: str, ctx: str = "") -> None:
    hit = _BANNED.search(text or "")
    assert hit is None, (
        f"Internal cadence token leaked into public surface ({ctx}): "
        f"{hit.group(0)!r} in {text!r}"
    )


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(public_router.router)
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────
# Helper-level unit tests — pin the sanitization itself.
# ─────────────────────────────────────────────────────────────────

def test_strip_internal_tokens_removes_day_phase_audit_pr_task_and_issue_refs():
    inp = (
        "Day-107a: IT services cohort (Audit#7 P0 followup, PR #498, "
        "Phase B.1 drain, Task #123, see issue #503)."
    )
    out = _strip_internal_tokens(inp)
    _assert_no_internal_tokens(out, "strip_internal_tokens output")
    # The substantive vocabulary survives.
    assert "IT services cohort" in out


def test_strip_internal_tokens_handles_empty_and_none():
    assert _strip_internal_tokens("") == ""
    assert _strip_internal_tokens(None) == ""  # type: ignore[arg-type]


def test_public_description_falls_back_to_generic_when_all_tokens():
    entry = {"rationale": "Day-107a"}
    assert _public_description(entry) == "Model updated."


def test_public_description_capitalises_first_letter_after_strip():
    entry = {"rationale": "Day-107a: it services cohort overrides"}
    out = _public_description(entry)
    assert out.startswith("It services cohort overrides") or out.startswith(
        "IT services cohort overrides"
    )
    _assert_no_internal_tokens(out, "public_description")


def test_public_manifest_entry_drops_version_id_and_rationale():
    raw_entry = {
        "version_id": "v_day107a_it_services_cohort_2026_05_23",
        "applied_at": None,
        "scope": {"tickers": ["TCS"], "fields": ["fair_value"]},
        "rationale": "Day-107a: IT services cohort overrides (WACC tighten)",
    }
    public = public_manifest_entry(raw_entry)
    assert "version_id" not in public, "version_id must not surface"
    assert "rationale" not in public, "rationale must not surface"
    assert "description" in public
    assert public["fields_affected"] == ["fair_value"]
    _assert_no_internal_tokens(public["description"], "public.description")


def test_public_manifest_entry_preserves_wildcard_fields():
    raw_entry = {
        "version_id": "v_init_2026_05_22",
        "scope": {"tickers": "*", "fields": "*"},
        "rationale": "Day-94 migration anchor — invalidate everything",
    }
    public = public_manifest_entry(raw_entry)
    assert public["fields_affected"] == ["*"]
    _assert_no_internal_tokens(public["description"], "init entry")


# ─────────────────────────────────────────────────────────────────
# Endpoint-level: /api/v1/public/manifest-history/{ticker} (anon).
# ─────────────────────────────────────────────────────────────────

def test_anon_manifest_history_strips_version_id_and_internal_tokens(
    client: TestClient,
) -> None:
    """Feeds the spec example through the live endpoint and asserts
    the contract: TCS is in the IT services cohort, so the response
    MUST contain an entry derived from the v_day107a_* manifest row;
    the anon shape MUST NOT include the version_id, and the
    description MUST NOT contain "Day-107a" or any other internal
    cadence token.
    """
    r = client.get("/api/v1/public/manifest-history/TCS.NS")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ticker"] == "TCS.NS"
    assert isinstance(body["entries"], list)
    assert len(body["entries"]) >= 1
    for entry in body["entries"]:
        assert "version_id" not in entry, (
            f"anon response must not include version_id; got entry={entry!r}"
        )
        assert "rationale" not in entry, (
            f"anon response must not include raw rationale; got entry={entry!r}"
        )
        assert "description" in entry
        _assert_no_internal_tokens(
            entry["description"],
            ctx=f"entry applied_at={entry.get('applied_at')!r}",
        )


def test_anon_manifest_history_sets_vary_authorization(
    client: TestClient,
) -> None:
    """The CDN must vary the cached anon response by Authorization
    so we never serve the authed shape to an anon caller (or vice
    versa)."""
    r = client.get("/api/v1/public/manifest-history/TCS.NS")
    assert r.status_code == 200
    vary = r.headers.get("Vary", "")
    assert "Authorization" in vary, f"missing Vary: Authorization; got {vary!r}"


def test_anon_manifest_history_unknown_ticker_still_sanitized(
    client: TestClient,
) -> None:
    """Wildcard entries apply to unknown tickers too; they must
    still be sanitized."""
    r = client.get("/api/v1/public/manifest-history/ZZZNONEXISTENT.NS")
    assert r.status_code == 200
    for entry in r.json()["entries"]:
        assert "version_id" not in entry
        _assert_no_internal_tokens(entry.get("description", ""))


# ─────────────────────────────────────────────────────────────────
# Spec example from Task #123: feed a synthetic IT-services entry
# through public_manifest_entry and assert the projected shape.
# ─────────────────────────────────────────────────────────────────

def test_task_123_spec_example_serialization() -> None:
    entry = {
        "version_id": "v_day107a_it_services",
        "applied_at": None,
        "scope": {"tickers": ["TCS"], "fields": ["fair_value"]},
        "rationale": "Day-107a IT services cohort applied",
    }
    public = public_manifest_entry(entry)
    # No version_id key.
    assert "version_id" not in public
    # No raw rationale key.
    assert "rationale" not in public
    # Description is the rationale-equivalent, sanitized.
    assert "Day-107a" not in public["description"]
    assert "IT services cohort" in public["description"]


# ─────────────────────────────────────────────────────────────────
# Sector landing-page audit — /api/v1/public/sector/{slug}.
# ─────────────────────────────────────────────────────────────────

def test_sector_endpoint_drops_manifest_ref_and_sanitizes_notes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The IT services cohort's `notes` field contains 'Day-107a' twice
    in the source registry. The public endpoint must strip those tokens
    AND must not surface the `manifest_ref` field at all."""
    # Force the aggregate to recompute (the endpoint caches on a
    # cache key, so a previous test run would mask the change).
    from backend.services.cache_service import cache as _cache
    try:
        _cache.delete("public:sector-page:v1:it-services")
    except Exception:
        pass

    r = client.get("/api/v1/public/sector/it-services")
    assert r.status_code == 200, r.text
    body = r.json()
    # manifest_ref is gone (or, defensively, falsy).
    assert "manifest_ref" not in body or not body.get("manifest_ref"), (
        f"sector response must not surface manifest_ref; got {body.get('manifest_ref')!r}"
    )
    # cohort_notes survives but no longer contains "Day-107a".
    notes = body.get("cohort_notes") or ""
    _assert_no_internal_tokens(notes, ctx="cohort_notes")
    # The substantive description survives.
    assert "Tier-1 IT services" in notes or "IT services" in notes.lower()


# ─────────────────────────────────────────────────────────────────
# Codebase audit pass — every rationale string in the live MANIFEST
# survives sanitization without becoming meaningless.
# ─────────────────────────────────────────────────────────────────

def test_every_live_manifest_entry_sanitizes_to_nonempty_description():
    from backend.services.cache_invalidation_manifest import MANIFEST
    for entry in MANIFEST:
        desc = _public_description(entry)
        assert desc, f"empty description for entry {entry.get('version_id')!r}"
        _assert_no_internal_tokens(
            desc,
            ctx=f"MANIFEST entry version_id={entry.get('version_id')!r}",
        )


# ─────────────────────────────────────────────────────────────────
# Fix #566-followup (2026-05-24): the original Phase pattern
# matched only "Phase X" / "Phase X.N". Phase G/H/I rationales use
# the extended forms "Phase G-intel-phase1 (c)" and "Phase
# H-frontend (Block II)", which leaked the suffix onto the
# anon-facing analysis page (HDFCBANK.NS "Why we changed"). These
# tests pin the broader compound-label match and the version_id
# omission contract for the Phase G/H/I rows specifically.
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rationale",
    [
        "Phase G-intel-phase1 (c): expose Anthropic-extracted "
        "concall_signals on the public analysis surface.",
        "Phase H-frontend (Block II): expose Anthropic-extracted "
        "ar_signals (segments / capex / RPT / auditor flags / "
        "contingent liabilities / outlook) on the analysis page.",
        "Phase I-frontend (Block II): expose bank operational KPIs "
        "(branches / ATMs / customers / GNPA / NNPA / PCR / CASA / "
        "cost-to-income / credit-deposit) on the analysis surface for "
        "the 38 commercial banks in PURE_BANK_TICKERS_FOR_DE.",
    ],
)
def test_strip_strips_extended_phase_forms(rationale: str) -> None:
    """The compound `Phase X-suffix (qualifier)` label must be removed
    wholesale, leaving the substantive description intact."""
    out = _strip_internal_tokens(rationale)
    _assert_no_internal_tokens(out, ctx="extended-phase rationale")
    # The substantive vocabulary (the "expose ..." description) must
    # survive — we don't want to nuke the entire rationale.
    assert "expose" in out.lower()
    # And no stray "frontend (Block II)" / "-intel-phase1 (c)"
    # suffix is left dangling.
    assert "Block II" not in out
    assert "intel-phase1" not in out
    assert "frontend" not in out.lower().split(":")[0]


@pytest.mark.parametrize(
    "version_id,rationale",
    [
        (
            "v_phase_g_intel_signals_2026_05_26",
            "Phase G-intel-phase1 (c): expose Anthropic-extracted "
            "concall_signals on the public analysis surface.",
        ),
        (
            "v_phase_h_ar_signals_2026_05_26",
            "Phase H-frontend (Block II): expose Anthropic-extracted "
            "ar_signals on the analysis page.",
        ),
        (
            "v_phase_i_bank_kpis_2026_05_26",
            "Phase I-frontend (Block II): expose bank operational KPIs "
            "on the analysis surface.",
        ),
    ],
)
def test_phase_ghi_entries_drop_version_id_and_internal_tokens(
    version_id: str, rationale: str
) -> None:
    """Phase G / H / I entries must (a) omit ``version_id`` from the
    anon shape and (b) strip every cadence token from the description.
    Regression guard for the HDFCBANK.NS leak that motivated this fix.
    """
    raw_entry = {
        "version_id": version_id,
        "applied_at": None,
        "scope": {"tickers": "*", "fields": ["ar_signals"]},
        "rationale": rationale,
    }
    public = public_manifest_entry(raw_entry)
    assert "version_id" not in public, (
        f"version_id must not surface; got {public!r}"
    )
    assert "rationale" not in public
    assert "description" in public
    desc = public["description"]
    _assert_no_internal_tokens(desc, ctx=f"public.description for {version_id}")
    # The leaked chip-text strings must not appear anywhere in the
    # description, even as fragments.
    assert "Phase G" not in desc
    assert "Phase H" not in desc
    assert "Phase I" not in desc
    assert "Block II" not in desc
    assert "intel-phase1" not in desc
    # The internal version_id token itself must not leak either.
    assert "v_phase_" not in desc


def test_strip_handles_phase_letter_pr_number_compound() -> None:
    """`Phase C.2 PR 1: ...` (Phase C.2 PR-1 style cadence) must
    strip both halves cleanly."""
    out = _strip_internal_tokens(
        "Phase C.2 PR 1: drop divergent TypeError scoring fallback."
    )
    _assert_no_internal_tokens(out, ctx="phase + bare-PR rationale")
    assert "TypeError" in out  # substantive vocabulary survives
