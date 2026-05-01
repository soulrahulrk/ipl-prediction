from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False))


def init_engine(database_url: str) -> None:
    global engine
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
    SessionLocal.configure(bind=engine)


def get_db_session():
    return SessionLocal()


def init_db() -> None:
    if engine is None:
        raise RuntimeError("Database engine is not initialized")
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
