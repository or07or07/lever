"""Lever — Database setup.

Supports both SQLite (local dev) and PostgreSQL (production).
The DATABASE_URL environment variable controls which backend is used:

  SQLite:     sqlite:///data/lever.db        (default, zero-config)
  PostgreSQL: postgresql://user:pass@host/db   (production)
"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import settings, BASE_DIR

# ---------------------------------------------------------------------------
# Engine configuration — backend-aware
# ---------------------------------------------------------------------------
_url = settings.database_url
_is_sqlite = _url.startswith("sqlite")
_is_postgres = _url.startswith("postgresql")

if _is_sqlite:
    # Ensure data directory exists for SQLite
    (BASE_DIR / "data").mkdir(exist_ok=True)

    engine = create_engine(
        _url,
        connect_args={"check_same_thread": False},
        echo=settings.debug,
    )

    # SQLite: enable WAL mode and foreign key enforcement
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, conn_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

elif _is_postgres:
    engine = create_engine(
        _url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=settings.debug,
    )

    @event.listens_for(engine, "connect")
    def set_pg_options(dbapi_conn, conn_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET statement_timeout = '30s'")
        cursor.close()

else:
    engine = create_engine(_url, echo=settings.debug)


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
def get_db():
    """Yields a DB session; always closes on completion or error."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Health check utility
# ---------------------------------------------------------------------------
def check_db_connection() -> bool:
    """Return True if the database is reachable, False otherwise."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
