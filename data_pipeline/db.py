# data_pipeline/db.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL")
# SQLAlchemy ≥1.4 dropped the legacy ``postgres://`` scheme — Aiven/Heroku
# URIs still use it, so normalise before create_engine.
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
engine = create_engine(DATABASE_URL) if DATABASE_URL else None
Session = sessionmaker(bind=engine) if engine else None


def get_db():
    if Session is None:
        raise RuntimeError("DATABASE_URL not set")
    db = Session()
    try:
        yield db
    finally:
        db.close()
