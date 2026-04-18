# data_pipeline/db.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL")
# SQLAlchemy ≥1.4 dropped the legacy ``postgres://`` scheme — Aiven/Heroku
# URIs still use it, so normalise before create_engine.
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

# connect_timeout=3: if the DB host is unreachable (deleted, firewall,
# wrong URL), fail in 3 seconds instead of the OS default 30-120s.
# Without this, every _get_pipeline_session() call blocks for 30s+
# on a dead DB — and there are 8 sequential calls per analysis request
# = 4 MINUTES of pure timeout waiting.
import logging as _log
_logger = _log.getLogger("yieldiq.db")
if DATABASE_URL:
    _host = DATABASE_URL.split("@")[-1].split("/")[0] if "@" in DATABASE_URL else "unknown"
    _logger.info("DB_INIT: engine creating for host=%s", _host)
engine = create_engine(
    DATABASE_URL,
    connect_args={"connect_timeout": 30},  # Aiven free tier can take 15-20s on cold start
    pool_pre_ping=True,        # detect stale connections before use
    pool_recycle=300,           # recycle connections every 5 min
    # Sized for 4 uvicorn workers on Railway against Aiven Postgres
    # (free tier ceiling ~20 concurrent connections). Per-worker:
    # pool_size 3 + max_overflow 2 = 5 max → 4 workers × 5 = 20 total.
    # With parallel ThreadPoolExecutor inside a worker (10 parallel
    # sub-computes), 3 baseline + 2 overflow is enough since most
    # sub-computes don't touch DB; those that do (TTM financials,
    # promoter pledge, earnings date, bulk deals, shareholding,
    # EBIT/interest) are staggered across the request lifecycle.
    pool_size=3,
    max_overflow=2,
    # If the pool is exhausted, fail in 10s instead of hanging 30+s.
    pool_timeout=10,
) if DATABASE_URL else None
if engine:
    _logger.info("DB_INIT: engine created OK")
else:
    _logger.warning("DB_INIT: engine is None (DATABASE_URL not set)")
Session = sessionmaker(bind=engine) if engine else None


def get_db():
    if Session is None:
        raise RuntimeError("DATABASE_URL not set")
    db = Session()
    try:
        yield db
    finally:
        db.close()
