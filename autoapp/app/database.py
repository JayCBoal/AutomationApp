import os
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session


@event.listens_for(Engine, "connect")
def _enforce_foreign_keys_on_sqlite(connection, _record):
    """
    SQLite ignores foreign keys unless asked not to, on every connection. Without this,
    deleting a job step would leave its parameters behind, where MariaDB removes them.
    """
    if isinstance(connection, sqlite3.Connection):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# Defaults to local SQLite file for development or MariaDB/PostgreSQL via env var
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./autoapp.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI Dependency providing transactional DB session per request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()