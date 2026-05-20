"""Day-47/48 (2026-05-20): post-checkout activation + 429 upgrade link.

Source-text regression guards for the Week-5 monetization PR:
  - /verify-subscription dispatches send_upgrade_confirmation_email
    off a daemon thread and returns redirect_to=/account?just_upgraded=
  - email_service exposes send_upgrade_confirmation_email with
    tier-specific copy for analyst / pro / student
  - middleware/auth.py emits structured 429 detail with
    error=quota_exceeded + upgrade_link=/pricing?ref=quota_wall
  - home page quota warning fires at remaining<=3 (was <=1)
  - UpgradeActivationModal exists with tier-specific copy + dismiss
    persistence
  - account/page.tsx mounts <UpgradeActivationModal/>
"""
from __future__ import annotations
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_PAYMENTS = _ROOT / "backend" / "routers" / "payments.py"
_EMAIL = _ROOT / "backend" / "services" / "email_service.py"
_AUTH = _ROOT / "backend" / "middleware" / "auth.py"
_HOME = _ROOT / "frontend" / "src" / "app" / "(app)" / "home" / "page.tsx"
_MODAL = _ROOT / "frontend" / "src" / "components" / "account" / "UpgradeActivationModal.tsx"
_ACCOUNT = _ROOT / "frontend" / "src" / "app" / "(app)" / "account" / "page.tsx"


# ── /verify-subscription wiring ──────────────────────────────


def test_verify_subscription_dispatches_confirmation_email():
    src = _PAYMENTS.read_text(encoding="utf-8")
    assert "send_upgrade_confirmation_email" in src
    # Must be off-thread so SMTP latency can't block the redirect
    assert "threading.Thread(" in src
    assert "daemon=True" in src


def test_verify_subscription_returns_redirect_to_with_just_upgraded():
    src = _PAYMENTS.read_text(encoding="utf-8")
    assert '"redirect_to"' in src
    assert "/account?just_upgraded=" in src


# ── email_service tier-specific copy ──────────────────────────


def test_send_upgrade_confirmation_email_defined():
    src = _EMAIL.read_text(encoding="utf-8")
    assert "def send_upgrade_confirmation_email(" in src


def test_upgrade_email_has_tier_specific_blocks():
    src = _EMAIL.read_text(encoding="utf-8")
    # Each paid tier must have its own copy block — the audit (P1)
    # called out generic copy as the primary friction.
    for tier in ("analyst", "pro", "student"):
        assert tier in src.lower()


# ── 429 upgrade_link payload ─────────────────────────────────


def test_analysis_quota_429_returns_structured_detail():
    src = _AUTH.read_text(encoding="utf-8")
    assert '"error": "quota_exceeded"' in src
    assert '"upgrade_link": "/pricing?ref=quota_wall"' in src
    assert '"limit"' in src
    assert '"used"' in src


# ── home quota warning threshold ─────────────────────────────


def test_home_quota_warning_fires_at_three_remaining():
    src = _HOME.read_text(encoding="utf-8")
    assert "remaining <= 3" in src
    # And the old threshold must be gone — otherwise both fire
    assert "remaining <= 1" not in src


# ── UpgradeActivationModal ───────────────────────────────────


def test_activation_modal_component_exists():
    assert _MODAL.exists(), "UpgradeActivationModal.tsx missing"


def test_activation_modal_handles_three_tiers():
    src = _MODAL.read_text(encoding="utf-8")
    for tier in ("analyst", "pro", "student"):
        assert f'{tier}:' in src or f'"{tier}"' in src


def test_activation_modal_reads_just_upgraded_param():
    src = _MODAL.read_text(encoding="utf-8")
    assert 'just_upgraded' in src
    assert "useSearchParams" in src


def test_activation_modal_persists_dismissal():
    src = _MODAL.read_text(encoding="utf-8")
    # Storage key pattern — prevents the modal re-firing on every
    # /account visit after the user has already seen it.
    assert "dismissed_upgrade_modal_" in src
    assert "localStorage" in src


def test_activation_modal_mounted_in_account_page():
    src = _ACCOUNT.read_text(encoding="utf-8")
    assert "UpgradeActivationModal" in src
    assert "<UpgradeActivationModal" in src
