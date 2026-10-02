"""Stamp an existing database only when it exactly matches current ORM metadata."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from backend.app.config import settings
from backend.app.db.base import Base
from backend.app.db.session import build_engine
from backend.app.models import Mention  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely stamp an existing schema after read-only Alembic comparison."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create Alembic version tracking at head after a zero-diff comparison.",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Explicitly allow stamping the configured non-local MIGRATION_DATABASE_URL.",
    )
    parser.add_argument(
        "--from-app-config",
        action="store_true",
        help="Read DATABASE_URL from .env in-process without printing it.",
    )
    args = parser.parse_args()

    database_url = settings.database_url if args.from_app_config else os.environ.get("MIGRATION_DATABASE_URL")
    if not database_url:
        print("baseline=refused reason=database URL is not configured")
        return 2

    url = make_url(database_url)
    is_local = url.host in {"localhost", "127.0.0.1", "::1"}
    if not is_local and not args.allow_remote:
        print("baseline=refused reason=remote target requires --allow-remote")
        return 2

    config = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    engine = build_engine(database_url, connect_args={"connect_timeout": 10})
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table("mentions", schema="public"):
                print("baseline=refused reason=public.mentions does not exist")
                return 2

            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True, "compare_server_default": True},
            )
            differences = compare_metadata(context, Base.metadata)
            if differences:
                categories = sorted({str(difference[0][0]) for difference in differences})
                print("baseline=refused schema_differences=" + ",".join(categories))
                return 2
            print("schema_comparison=zero_differences")

            version_table = connection.execute(
                text("SELECT to_regclass('public.alembic_version')")
            ).scalar_one()
            if version_table is not None:
                revisions = connection.execute(
                    text("SELECT version_num FROM public.alembic_version")
                ).scalars().all()
                if revisions == [head]:
                    print("baseline=already_at_head")
                    return 0
                print("baseline=refused reason=version table exists with a non-head revision")
                return 2
        if not args.apply:
            print("baseline=not_applied use_--apply_after_review")
            return 0

        if args.allow_remote:
            os.environ["ALLOW_REMOTE_MIGRATIONS"] = "true"
        command.stamp(config, "head")
        print("baseline=stamped revision=" + str(head))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())