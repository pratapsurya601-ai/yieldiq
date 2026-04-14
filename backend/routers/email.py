# backend/routers/email.py
# ═══════════════════════════════════════════════════════════════
# Email management endpoints: unsubscribe.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/api/v1/email", tags=["email"])


@router.get("/test")
async def test_email():
    """Test: send a welcome email to the configured from address."""
    from backend.services.email_service import send_welcome_email, SENDGRID_API_KEY, FROM_EMAIL
    result = {
        "sendgrid_configured": bool(SENDGRID_API_KEY),
        "api_key_length": len(SENDGRID_API_KEY),
        "from_email": FROM_EMAIL,
    }
    if not SENDGRID_API_KEY:
        result["error"] = "SENDGRID_API_KEY not set"
        return result
    # Test raw SendGrid API directly
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        message = Mail(
            from_email=FROM_EMAIL,
            to_emails=FROM_EMAIL,
            subject="YieldIQ Test Email",
            html_content="<h2>Test email from YieldIQ</h2><p>If you see this, SendGrid is working!</p>",
        )
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        result["status_code"] = response.status_code
        result["email_sent"] = response.status_code in (200, 201, 202)
        result["sent_to"] = FROM_EMAIL
        if response.status_code not in (200, 201, 202):
            result["body"] = response.body.decode() if response.body else ""
    except ImportError:
        result["error"] = "sendgrid package not installed on Railway"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"
    return result


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(
    email: str = Query(...),
    token: str = Query(""),
):
    """
    Unsubscribe a user from YieldIQ emails.
    Shows a simple confirmation page.
    """
    from backend.services.email_service import (
        verify_unsubscribe_token,
        mark_user_unsubscribed,
    )

    # Verify token if provided (optional for simple flow)
    if token and not verify_unsubscribe_token(email, token):
        return HTMLResponse(
            content=_unsubscribe_page(
                success=False,
                message="Invalid unsubscribe link. Please try again or contact support.",
            ),
            status_code=400,
        )

    success = mark_user_unsubscribed(email)

    if success:
        return HTMLResponse(
            content=_unsubscribe_page(
                success=True,
                message=f"You have been successfully unsubscribed. "
                        f"You will no longer receive emails from YieldIQ.",
            ),
        )
    else:
        return HTMLResponse(
            content=_unsubscribe_page(
                success=True,
                message="Your unsubscribe request has been noted. "
                        "You will no longer receive emails from YieldIQ.",
            ),
        )


def _unsubscribe_page(success: bool, message: str) -> str:
    """Render a simple branded unsubscribe confirmation page."""
    icon = "&#10003;" if success else "&#10007;"
    color = "#059669" if success else "#DC2626"
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>YieldIQ - Unsubscribe</title>
    </head>
    <body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
                 background:#F9FAFB;display:flex;justify-content:center;align-items:center;min-height:100vh;">
      <div style="max-width:480px;background:#FFF;border-radius:12px;padding:40px;text-align:center;
                  box-shadow:0 1px 3px rgba(0,0,0,0.1);">
        <div style="width:64px;height:64px;border-radius:50%;background:{color};color:#FFF;
                    font-size:32px;line-height:64px;margin:0 auto 20px;">{icon}</div>
        <h1 style="color:#111827;font-size:22px;margin:0 0 12px;">
          {'Unsubscribed' if success else 'Error'}
        </h1>
        <p style="color:#6B7280;font-size:15px;line-height:1.6;margin:0 0 24px;">
          {message}
        </p>
        <a href="https://yieldiq.in"
           style="display:inline-block;background:#1D4ED8;color:#FFF;padding:10px 24px;
                  border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;">
          Go to YieldIQ
        </a>
      </div>
    </body>
    </html>
    """
