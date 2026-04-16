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
engine = create_engine(
    DATABASE_URL,
    connect_args={"connect_timeout": 3},
    pool_pre_ping=True,        # detect stale connections before use
    pool_recycle=300,           # recycle connections every 5 min
) if DATABASE_URL else None
Session = sessionmaker(bind=engine) if engine else None


def get_db():
    if Session is None:
        raise RuntimeError("DATABASE_URL not set")
    db = Session()
    try:
        yield db
    finally:
        db.close()
