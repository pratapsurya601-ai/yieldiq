"""Day-49 (2026-05-20): student / CA articleship verification automation.

Source-text regression guards. Verifies:
  - /billing/student-verify endpoint exists, requires auth, enforces
    file size + MIME type, stores to Supabase Storage and inserts a
    student_applications row
  - /admin/student-applications queue gated by require_admin, mints
    short-lived signed URLs
  - approve route flips tier to "student" + dispatches approval email
  - reject route writes rejection_reason + dispatches rejection email
  - email_service.send_student_application_email supports both
    approved and rejected paths
  - migration 018_student_applications.sql defines the table with
    proper constraints and indexes
  - frontend page /account/student-verify wires multipart POST to
    the backend endpoint
"""
from __future__ import annotations
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_ROUTER = _ROOT / "backend" / "routers" / "student_verify.py"
_EMAIL = _ROOT / "backend" / "services" / "email_service.py"
_MAIN = _ROOT / "backend" / "main.py"
_MIGRATION = _ROOT / "db" / "migrations" / "018_student_applications.sql"
_FRONTEND_PAGE = _ROOT / "frontend" / "src" / "app" / "(app)" / "account" / "student-verify" / "page.tsx"


# ── Router file structure ────────────────────────────────────


def test_student_verify_router_file_exists():
    assert _ROUTER.exists(), "backend/routers/student_verify.py missing"


def test_student_verify_router_mounted_in_main():
    src = _MAIN.read_text(encoding="utf-8")
    assert "student_verify" in src
    assert "include_router(student_verify_router.router)" in src


# ── Submission endpoint ──────────────────────────────────────


def test_submit_endpoint_defined_with_auth():
    src = _ROUTER.read_text(encoding="utf-8")
    assert '@router.post("/billing/student-verify"' in src
    assert "Depends(get_current_user)" in src
    assert "UploadFile" in src
    assert "full_name" in src
    assert "institution" in src


def test_submit_validates_file_size_and_mime():
    src = _ROUTER.read_text(encoding="utf-8")
    # 5 MB cap
    assert "MAX_UPLOAD_BYTES = 5 * 1024 * 1024" in src
    assert "status_code=413" in src
    # MIME allow-list
    assert "ALLOWED_CONTENT_TYPES" in src
    assert "application/pdf" in src
    assert "status_code=415" in src


def test_submit_writes_to_storage_and_table():
    src = _ROUTER.read_text(encoding="utf-8")
    assert 'STORAGE_BUCKET = "student-ids"' in src
    assert "client.storage.from_(STORAGE_BUCKET).upload" in src
    assert 'client.table("student_applications").insert' in src
    # Path keyed by user_id, not email, to avoid leaking emails
    assert 'f"{user_id}/' in src


# ── Admin queue ──────────────────────────────────────────────


def test_admin_queue_requires_admin():
    src = _ROUTER.read_text(encoding="utf-8")
    assert '@router.get("/admin/student-applications")' in src
    assert "Depends(require_admin)" in src


def test_admin_queue_returns_signed_urls():
    src = _ROUTER.read_text(encoding="utf-8")
    # Signed URL with TTL — never expose the bucket publicly
    assert "create_signed_url" in src
    assert "3600" in src  # 1h TTL


# ── Approve / reject ─────────────────────────────────────────


def test_approve_flips_tier_and_sends_email():
    src = _ROUTER.read_text(encoding="utf-8")
    assert "/admin/student-applications/{application_id}/approve" in src
    assert 'set_user_tier(app["email"], "student")' in src
    assert "send_student_application_email" in src
    # Idempotency guard — approving twice must 409
    assert "Application already" in src


def test_reject_records_reason_and_sends_email():
    src = _ROUTER.read_text(encoding="utf-8")
    assert "/admin/student-applications/{application_id}/reject" in src
    assert "rejection_reason" in src
    assert 'args=(app["email"], "rejected"' in src


# ── Email service ────────────────────────────────────────────


def test_send_student_application_email_defined():
    src = _EMAIL.read_text(encoding="utf-8")
    assert "def send_student_application_email(" in src
    # Both decisions handled
    assert '"approved"' in src
    assert '"rejected"' in src
    # Honours opt-out
    assert "is_user_unsubscribed(email)" in src


# ── Migration ────────────────────────────────────────────────


def test_migration_defines_student_applications_table():
    assert _MIGRATION.exists(), "018_student_applications.sql missing"
    src = _MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS student_applications" in src
    # Status enum guard so a bug can't write an arbitrary string
    assert "CHECK (status IN ('pending', 'approved', 'rejected'))" in src
    # Both indexes
    assert "idx_student_apps_status" in src
    assert "idx_student_apps_user_created" in src


# ── Frontend page ────────────────────────────────────────────


def test_frontend_student_verify_page_exists():
    assert _FRONTEND_PAGE.exists(), "frontend student-verify page missing"


def test_frontend_posts_multipart_to_backend():
    src = _FRONTEND_PAGE.read_text(encoding="utf-8")
    assert "/api/v1/billing/student-verify" in src
    assert "FormData()" in src
    assert 'fd.append("file"' in src
    assert 'fd.append("full_name"' in src
    assert 'fd.append("institution"' in src
    # Enforces the same 5MB cap client-side
    assert "5 * 1024 * 1024" in src
