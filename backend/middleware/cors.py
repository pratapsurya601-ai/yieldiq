# backend/middleware/cors.py
# CORS configuration for the YieldIQ API.
from __future__ import annotations

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "https://yieldiq.in",
    "https://www.yieldiq.in",
    "https://app.yieldiq.in",
    "https://yieldiq-gules.vercel.app",
]

# Also allow any Vercel preview deployment
ALLOWED_ORIGIN_REGEX = r"https://.*\.vercel\.app"
