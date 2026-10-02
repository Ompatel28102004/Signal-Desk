from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from backend.app.config import settings


def build_engine(database_url: str, **options: Any) -> Engine:
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    return create_engine(url, pool_pre_ping=True, **options)


engine = build_engine(settings.database_url) if settings.database_url else None


def get_session() -> Generator[Session, None, None]:
    if engine is None:
        raise RuntimeError("DATABASE_URL is not configured")
    with Session(engine) as session:
        yield session