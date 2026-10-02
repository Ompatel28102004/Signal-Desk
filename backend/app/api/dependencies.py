import logging
from collections.abc import Generator

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.ai.service import AIInsightsService
from backend.app.config import settings
from backend.app.db.session import engine
from backend.app.ingestion.manager import IngestionManager
from backend.app.ingestion.sources import build_ingestion_manager


logger = logging.getLogger(__name__)


def get_database_session() -> Generator[Session, None, None]:
    if engine is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    session = Session(engine)
    try:
        yield session
    except SQLAlchemyError as error:
        session.rollback()
        logger.error("api.database.failed", extra={"error_type": type(error).__name__})
        raise HTTPException(status_code=503, detail="Database operation failed") from error
    finally:
        session.close()


def get_ingestion_manager() -> IngestionManager:
    return build_ingestion_manager(settings)


def get_ai_insights_service() -> AIInsightsService:
    return AIInsightsService()