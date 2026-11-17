"""Alembic environment: connects migrations to our models and settings."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import app.database.models  # noqa: F401  (loads every model into Base.metadata)
from app.core.config import get_settings
from app.database.base import Base

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers=False: by default fileConfig switches off every
    # logger that already exists. When migrations run inside the app's process
    # (as in the test suite), that silently killed all of QuickServe's logs.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
# Tests (and CI) can point migrations at another database with: alembic -x db_url=...
DB_URL = context.get_x_argument(as_dictionary=True).get("db_url") or get_settings().database_url


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql` prints the SQL instead of running it.
    Useful for review: a DBA (or you) can read exactly what a migration will do."""
    context.configure(url=DB_URL, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(DB_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
