# backend/routers/student_verify.py
# ─────────────────────────────────────────────────────────────
# Day-49 (2026-05-20): student / CA articleship tier-verification
# automation.
#
# Before this router existed the flow was:
#   1. user signs up
#   2. user emails hello@yieldiq.in with ID proof
#   3. ops manually flips tier in Supabase
#   4. user gets no notification back
#
# After:
#   1. user POSTs /api/v1/billing/student-verify with an image
#   2. file lands in Supabase Storage (bucket "student-ids", private)
#   3. row inserted into student_applications (status="pending")
#   4. ops sees it in /api/v1/admin/student-applications
#   5. ops approves → tier flips to "student" + approval email sent
#      ops rejects  → status=rejected + rejection email with reason
#
# All admin routes are gated by require_admin; the upload endpoint
# only requires get_current_user. The storage path is keyed by
# user_id, never email, so a user can't enumerate other users' IDs.
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend.middleware.auth import get_current_user
from backend.routers.admin import require_admin

logger = logging.getLogger("yieldiq.student_verify")

router = APIRouter(prefix="/api/v1", tags=["student-verify"])


# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────
# 5 MB upper bound — college IDs and CA articleship letters scanned
# at 200dpi land well under this. A 5MB cap also keeps Railway
# memory pressure predictable since we read the body into memory.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp", "application/pdf",
}
STORAGE_BUCKET = "student-ids"


# ─────────────────────────────────────────────────────────────
# Response models
# ─────────────────────────────────────────────────────────────
class StudentApplicationOut(BaseModel):
    id: str
    user_id: str
    email: str
    institution: str
    full_name: str
    status: str  # pending | approved | rejected
    storage_path: str
    rejection_reason: Optional[str] = None
    created_at: str
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None


class SubmitResponse(BaseModel):
    ok: bool
    application_id: str
    status: str = "pending"
    message: str


# ─────────────────────────────────────────────────────────────
# POST /billing/student-verify
# ─────────────────────────────────────────────────────────────
@router.post("/billing/student-verify", response_model=SubmitResponse)
async def submit_student_verification(
    file: UploadFile = File(..., description="College ID or CA enrolment letter (PDF/PNG/JPG, ≤5MB)"),
    full_name: str = Form(..., min_length=2, max_length=120),
    institution: str = Form(..., min_length=2, max_length=200),
    user: dict = Depends(get_current_user),
):
    """Submit a student-verification application.

    Body (multipart/form-data):
      file:         image/pdf of the ID proof
      full_name:    name as it appears on the ID
      institution:  college / CA institute name

    Returns the application_id and pending status. Approval happens
    asynchronously via the admin review queue.
    """
    # Validation block — file size + type. Reject up front rather
    # than uploading garbage to Supabase Storage.
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {content_type}. Accepted: PDF, PNG, JPG, WEBP.",
        )

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(contents)} bytes). Maximum is {MAX_UPLOAD_BYTES} bytes.",
        )
    if len(contents) < 1024:
        # Tiny files are almost always failed reads or empty uploads
        # — the smallest valid scanned college ID is well over 1KB.
        raise HTTPException(
            status_code=400,
            detail="File too small to be a valid ID document.",
        )

    user_id = user["user_id"]
    email = user["email"]
    application_id = str(uuid.uuid4())
    # Path is keyed by user_id (UUID) NOT email so the bucket layout
    # doesn't leak email addresses across rows. ext picked from the
    # content-type so the file extension matches reality regardless
    # of what the browser claimed.
    ext_map = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "application/pdf": "pdf",
    }
    ext = ext_map.get(content_type, "bin")
    storage_path = f"{user_id}/{application_id}.{ext}"

    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()

        # Upload to Supabase Storage. The bucket should be PRIVATE
        # (no public reads) — ops downloads via a signed URL when
        # reviewing.
        try:
            client.storage.from_(STORAGE_BUCKET).upload(
                path=storage_path,
                file=contents,
                file_options={"content-type": content_type, "upsert": "false"},
            )
        except Exception as storage_exc:
            logger.error(
                "student-verify: storage upload failed for user=%s path=%s: %s",
                user_id, storage_path, storage_exc,
            )
            raise HTTPException(
                status_code=500,
                detail="Could not store the ID document. Please retry in a minute.",
            )

        # Insert the application row. Status starts at "pending" —
        # the admin /approve and /reject routes are the only paths
        # that can advance it.
        now_iso = datetime.now(timezone.utc).isoformat()
        client.table("student_applications").insert({
            "id": application_id,
            "user_id": user_id,
            "email": email,
            "full_name": full_name.strip(),
            "institution": institution.strip(),
            "status": "pending",
            "storage_path": storage_path,
            "created_at": now_iso,
        }).execute()

        logger.info(
            "student-verify: application=%s user=%s institution=%r created",
            application_id, user_id, institution[:40],
        )
        return SubmitResponse(
            ok=True,
            application_id=application_id,
            status="pending",
            message="Your application has been submitted. We'll email you within 2 business days.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("student-verify submission failed: %r", exc)
        raise HTTPException(status_code=500, detail="Could not submit the application.")


# ─────────────────────────────────────────────────────────────
# GET /admin/student-applications  — review queue
# ─────────────────────────────────────────────────────────────
@router.get("/admin/student-applications")
async def list_student_applications(
    status: str = "pending",
    limit: int = 50,
    user: dict = Depends(require_admin),
):
    """Admin queue of student-verification applications. Default
    filter is status=pending; pass status=all to see everything."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be 1..500")
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        q = client.table("student_applications").select("*").order(
            "created_at", desc=True,
        ).limit(limit)
        if status != "all":
            q = q.eq("status", status)
        result = q.execute()
        rows = result.data or []

        # Annotate with a short-lived signed URL so ops can click
        # straight to the document. 1h is enough for a manual
        # review session and short enough that links shared in
        # logs expire on their own.
        for r in rows:
            try:
                signed = client.storage.from_(STORAGE_BUCKET).create_signed_url(
                    r["storage_path"], 3600,
                )
                r["signed_url"] = signed.get("signedURL") or signed.get("signed_url")
            except Exception as sig_exc:
                logger.warning(
                    "student-verify: signed-url failed for %s: %s",
                    r.get("storage_path"), sig_exc,
                )
                r["signed_url"] = None
        return {"applications": rows, "count": len(rows)}
    except Exception as exc:
        logger.exception("list_student_applications failed: %r", exc)
        raise HTTPException(status_code=500, detail="Could not load applications.")


# ─────────────────────────────────────────────────────────────
# POST /admin/student-applications/{id}/approve
# ─────────────────────────────────────────────────────────────
class RejectBody(BaseModel):
    reason: str


@router.post("/admin/student-applications/{application_id}/approve")
async def approve_student_application(
    application_id: str,
    user: dict = Depends(require_admin),
):
    """Approve a pending application:
       1. set status=approved + reviewed_at + reviewed_by
       2. flip the applicant's tier to "student"
       3. send approval email (off-thread)
    """
    try:
        from db.supabase_client import get_admin_client, set_user_tier
        client = get_admin_client()

        # Fetch + status-guard. Approving an already-approved or
        # rejected application is a no-op so ops can't accidentally
        # double-credit a user by clicking twice.
        row = client.table("student_applications").select("*").eq(
            "id", application_id,
        ).single().execute()
        app = row.data
        if not app:
            raise HTTPException(status_code=404, detail="Application not found")
        if app["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Application already {app['status']}",
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        client.table("student_applications").update({
            "status": "approved",
            "reviewed_at": now_iso,
            "reviewed_by": user["email"],
        }).eq("id", application_id).execute()

        # Tier flip. set_user_tier swallows errors and returns False
        # so we re-check explicitly — leaving the row "approved" with
        # the user still on free would be the worst possible state.
        ok = set_user_tier(app["email"], "student")
        if not ok:
            logger.error(
                "student-verify: tier flip FAILED for %s after approval. "
                "Row marked approved but tier untouched. Ops must reconcile.",
                app["email"],
            )

        # Send approval email off-thread so SMTP latency doesn't
        # block the admin's click.
        try:
            import threading
            from backend.services.email_service import send_student_application_email
            threading.Thread(
                target=send_student_application_email,
                args=(app["email"], "approved", app.get("full_name", ""), None),
                daemon=True,
            ).start()
        except Exception as eml_exc:
            logger.warning(
                "student-verify approval email dispatch failed: %s", eml_exc,
            )

        return {"ok": True, "status": "approved", "tier_flipped": ok}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("approve_student_application failed: %r", exc)
        raise HTTPException(status_code=500, detail="Could not approve.")


@router.post("/admin/student-applications/{application_id}/reject")
async def reject_student_application(
    application_id: str,
    body: RejectBody,
    user: dict = Depends(require_admin),
):
    """Reject an application with a free-text reason. Sends a
    rejection email with the reason so the user can resubmit."""
    reason = (body.reason or "").strip()
    if not reason or len(reason) > 500:
        raise HTTPException(
            status_code=400,
            detail="reason must be 1..500 chars",
        )
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        row = client.table("student_applications").select("*").eq(
            "id", application_id,
        ).single().execute()
        app = row.data
        if not app:
            raise HTTPException(status_code=404, detail="Application not found")
        if app["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Application already {app['status']}",
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        client.table("student_applications").update({
            "status": "rejected",
            "rejection_reason": reason,
            "reviewed_at": now_iso,
            "reviewed_by": user["email"],
        }).eq("id", application_id).execute()

        try:
            import threading
            from backend.services.email_service import send_student_application_email
            threading.Thread(
                target=send_student_application_email,
                args=(app["email"], "rejected", app.get("full_name", ""), reason),
                daemon=True,
            ).start()
        except Exception as eml_exc:
            logger.warning(
                "student-verify rejection email dispatch failed: %s", eml_exc,
            )

        return {"ok": True, "status": "rejected"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("reject_student_application failed: %r", exc)
        raise HTTPException(status_code=500, detail="Could not reject.")
