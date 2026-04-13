# backend/main.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ API — FastAPI entry point
# Wraps existing 20,000+ lines of valuation logic in REST API.
#
# RAILWAY DEPLOYMENT:
# 1. Create new Railway service → connect GitHub repo
# 2. Root directory: / (not /backend)
# 3. Start command: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
# 4. Add env vars from backend/.env.railway.example
# 5. Add custom domain: api.yieldiq.in
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

# PATH + ENV SETUP — must happen before ANY other imports
import sys, os
from pathlib import Path
_ROOT = str(Path(__file__).resolve().parent.parent)

# Load .env file if it exists (local dev — Railway uses dashboard env vars)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
except ImportError:
    pass
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_DASHBOARD = os.path.join(_ROOT, "dashboard")
if _DASHBOARD not in sys.path:
    sys.path.insert(0, _DASHBOARD)

# Verify path works before importing anything else
import importlib.util as _ilu
_logger_spec = _ilu.spec_from_file_location("utils.logger", os.path.join(_ROOT, "utils", "logger.py"))
if _logger_spec and _logger_spec.loader:
    _logger_mod = _ilu.module_from_spec(_logger_spec)
    sys.modules["utils.logger"] = _logger_mod
    _logger_spec.loader.exec_module(_logger_mod)
# Also pre-load utils package
_utils_spec = _ilu.spec_from_file_location("utils", os.path.join(_ROOT, "utils", "__init__.py"),
                                            submodule_search_locations=[os.path.join(_ROOT, "utils")])
if _utils_spec:
    _utils_mod = _ilu.module_from_spec(_utils_spec)
    sys.modules.setdefault("utils", _utils_mod)
    try:
        _utils_spec.loader.exec_module(_utils_mod)
    except Exception:
        pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import analysis, screener, portfolio, watchlist, alerts, market, auth
from backend.middleware.cors import ALLOWED_ORIGINS, ALLOWED_ORIGIN_REGEX

app = FastAPI(
    title="YieldIQ API",
    description="Institutional-grade DCF valuation API for Indian and global markets",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(screener.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(alerts.router)
app.include_router(market.router)


@app.get("/health")
async def health_check():
    """Health check endpoint for Railway/monitoring."""
    return {"status": "ok", "version": "1.0.0", "service": "yieldiq-api"}


@app.get("/")
async def root():
    """API root — links to documentation."""
    return {
        "message": "YieldIQ API",
        "version": "1.0.0",
        "docs": "/api/docs",
        "health": "/health",
    }
