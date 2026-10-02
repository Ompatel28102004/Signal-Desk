import os
from collections.abc import Generator

import pytest
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from backend.app.db.base import Base
from backend.app.db.session import build_engine
from backend.app.models import Mention  # noqa: F401


@pytest.fixture(scope="session")
def local_database_engine() -> Generator[Engine, None, None]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a local Supabase/PostgreSQL instance")

    host = make_url(database_url).host
    if host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("TEST_DATABASE_URL must point to localhost; refusing to use a remote database")

    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(local_database_engine: Engine) -> Generator[Session, None, None]:
    connection = local_database_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()