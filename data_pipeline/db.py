# data_pipeline/db.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL")
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
