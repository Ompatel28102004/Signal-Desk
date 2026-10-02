"""Check the configured PostgreSQL connection and the application's mentions schema."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from backend.app.config import settings
from backend.app.db.session import build_engine


REQUIRED_MENTION_COLUMNS = {
    "id",
    "source",
    "external_id",
    "keyword",
    "title",
    "content",
    "author",
    "url",
    "published_at",
    "collected_at",
    "engagement",
    "normalized_text",
    "content_hash",
    "relevance_score",
    "relevance_reason",
    "sentiment",
    "sentiment_score",
    "topic",
    "topic_score",
    "created_at",
    "updated_at",
}


def _connection_failure_reason(error: OperationalError) -> str:
    original = error.orig
    message = str(original).lower()

    if "password authentication failed" in message or "authentication failed" in message:
        return "Authentication failed; check the Supabase database user and password."
    if "could not translate host" in message or "name or service not known" in message:
        return "The database host could not be resolved; check the host in DATABASE_URL."
    if "timeout" in message or "timed out" in message:
        return "Connection timed out; check the host, port, SSL mode, and network access."
    if "ssl" in message or "tls" in message:
        return "TLS negotiation failed; check the Supabase connection string and sslmode."
    if "too many connections" in message:
        return "Supabase rejected the connection limit; close idle clients or use the pooler."
    return f"Connection failed ({type(original).__name__}); verify DATABASE_URL in the Supabase dashboard."


def main() -> int:
    if not settings.database_url:
        print("database_connection=failed")
        print("reason=DATABASE_URL is missing from the root .env file.")
        return 1

    try:
        url = make_url(settings.database_url)
    except Exception as error:
        print("database_connection=failed")
        print(f"reason=DATABASE_URL could not be parsed ({type(error).__name__}).")
        return 1

    if not url.host or url.host.startswith("@"):
        print("database_connection=failed")
        print(
            "reason=Malformed host in DATABASE_URL; URL-encode reserved password "
            "characters such as @ as %40."
        )
        return 1

    print(f"database_endpoint={url.host}:{url.port or 5432}/{url.database or ''}")
    if url.host.endswith("pooler.supabase.com") and url.query.get("sslmode") != "require":
        print("warning=Supabase pooler URLs should include sslmode=require.")

    engine = None
    try:
        engine = build_engine(
            settings.database_url,
            connect_args={"connect_timeout": 10},
        )
        with engine.connect() as connection:
            database_name = connection.execute(text("SELECT current_database()")).scalar_one()
            print("database_connection=success")
            print(f"connected_database={database_name}")

            table_exists = connection.execute(
                text("SELECT to_regclass('public.mentions')")
            ).scalar_one()
            if table_exists is None:
                print("mentions_table=missing")
                print(
                    "action=Create public.mentions in Supabase Table Editor or "
                    "apply the project migrations."
                )
                return 2

            existing_columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'mentions'"
                    )
                ).scalars()
            )
            missing_columns = sorted(REQUIRED_MENTION_COLUMNS - existing_columns)
            print("mentions_table=present")
            if missing_columns:
                print("mentions_schema=missing_columns " + ", ".join(missing_columns))
                return 2

            unique_constraints = set(
                connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'public.mentions'::regclass AND contype = 'u'"
                    )
                ).scalars()
            )
            if "uq_mentions_source_external_id" not in unique_constraints:
                print("mentions_schema=missing_constraint uq_mentions_source_external_id")
                print(
                    "action=Add UNIQUE (source, external_id) as constraint "
                    "uq_mentions_source_external_id."
                )
                return 2

            print("mentions_schema=ready")
            return 0
    except OperationalError as error:
        print("database_connection=failed")
        print("reason=" + _connection_failure_reason(error))
        return 1
    except SQLAlchemyError as error:
        print("database_check=failed")
        print(f"reason=Database query failed ({type(error).__name__}); no schema changes were made.")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())