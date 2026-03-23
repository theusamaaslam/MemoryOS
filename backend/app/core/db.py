from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.postgres_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def initialize_database() -> None:
    migration_dir = Path(__file__).resolve().parents[2] / "migrations"
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(64) PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"))
        applied = {row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))}
        for migration in sorted(migration_dir.glob("*.sql")):
            if migration.name in applied:
                continue
            connection.execute(text(migration.read_text()))
            connection.execute(text("INSERT INTO schema_migrations (version) VALUES (:version)"), {"version": migration.name})
