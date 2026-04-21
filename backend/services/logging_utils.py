# backend/services/logging_utils.py
# ═══════════════════════════════════════════════════════════════
# PII-safe logging helpers.
#
# Problem: email addresses were appearing in plain-text across
# logs that ship to Railway + Sentry. Ops can see them, which:
#   (a) leaks user identity to anyone with log access
#   (b) breaks GDPR-style "right to be forgotten" (logs retain
#       emails even after a user deletion)
#   (c) makes it harder to prove data handling discipline to
#       prospective acquirers / SEBI
#
# Fix: replace inline emails with a short deterministic hash
# that still lets ops correlate multiple log lines for the same
# user ("h:a1b2c3d4") without ever exposing the raw address.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import hashlib
from typing import Optional


def hash_email(email: Optional[str]) -> str:
    """Return a short stable prefix-hash for an email.

    Output is of the form `h:a1b2c3d4` (8 hex chars) — enough
    entropy to correlate log lines for the same user within a
    reasonable population (collision rate ~1 in 4 billion), but
    cryptographically useless for reversing.

    None / empty → "h:anon". Non-string input → coerced via str().
    """
    if not email:
        return "h:anon"
    s = str(email).strip().lower()
    if not s:
        return "h:anon"
    digest = hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]
    return f"h:{digest}"


def mask_email(email: Optional[str]) -> str:
    """Return a partially-masked email: 'v*****@example.com'.

    Useful when ops genuinely needs to see the domain (e.g., to
    debug email provider issues) but not the identity. Prefer
    hash_email() when the domain is not needed.
    """
    if not email:
        return "(anon)"
    s = str(email).strip()
    if "@" not in s:
        return "(invalid)"
    local, _, domain = s.partition("@")
    if not local:
        return f"***@{domain}"
    # First letter + "*****" + @domain
    return f"{local[0]}*****@{domain}"
