import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

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