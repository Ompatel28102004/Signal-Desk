from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.app.models import Mention
from backend.app.repositories.mentions import (
    add_or_get,
    get_by_id,
    get_by_source_external_id,
    list_mentions,
)
from backend.app.schemas.mention import MentionCreate


def test_database_connection(local_database_engine) -> None:
    with local_database_engine.connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1


def test_insert_and_duplicate_prevention(db_session: Session) -> None:
    payload = MentionCreate(
        source="module1-test",
        external_id=f"module1-test-{uuid4()}",
        keyword="launch",
        content="A product launch mention",
        engagement={"likes": 4, "shares": 2},
    )

    first, inserted_first = add_or_get(db_session, payload)
    duplicate, inserted_duplicate = add_or_get(db_session, payload)

    assert inserted_first is True
    assert inserted_duplicate is False
    assert duplicate.id == first.id
    assert duplicate.engagement == {"likes": 4, "shares": 2}
    assert db_session.scalar(
        select(func.count()).select_from(Mention).where(
            Mention.source == payload.source,
            Mention.external_id == payload.external_id,
        )
    ) == 1


def test_retrieval_and_filtering(db_session: Session) -> None:
    run_id = str(uuid4())
    newer = datetime.now(UTC)
    older = newer - timedelta(days=3)
    first, _ = add_or_get(
        db_session,
        MentionCreate(
            source="forum",
            external_id=f"module1-test-{run_id}-1",
            keyword="launch",
            published_at=newer,
            sentiment="positive",
            topic="product",
        ),
    )
    add_or_get(
        db_session,
        MentionCreate(
            source="forum",
            external_id=f"module1-test-{run_id}-2",
            keyword="launch",
            published_at=older,
            sentiment="neutral",
            topic="product",
        ),
    )
    add_or_get(
        db_session,
        MentionCreate(
            source="news",
            external_id=f"module1-test-{run_id}-3",
            keyword="launch",
            published_at=newer,
            sentiment="positive",
            topic="product",
        ),
    )

    assert get_by_id(db_session, first.id) is not None
    assert get_by_source_external_id(db_session, first.source, first.external_id) is not None
    matches = list_mentions(
        db_session,
        source="forum",
        keyword="launch",
        sentiment="positive",
        published_after=newer - timedelta(seconds=1),
    )
    assert [mention.id for mention in matches] == [first.id]