from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_local: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine

    if _engine is None:
        from app.core.config import get_settings

        _engine = create_engine(get_settings().database_url)
    return _engine


def get_session_local() -> sessionmaker[Session]:
    global _session_local

    if _session_local is None:
        _session_local = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _session_local


def get_db() -> Generator[Session, None, None]:
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()
