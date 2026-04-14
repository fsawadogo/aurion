"""Alembic environment configuration.

Reads DATABASE_URL from the environment and configures Alembic to use
the same SQLAlchemy ``Base.metadata`` that the application uses, so
``alembic revision --autogenerate`` can diff against the live models.

Usage:
    # Generate a migration after changing models
    alembic revision --autogenerate -m "describe the change"

    # Apply all pending migrations
    alembic upgrade head

    # Downgrade one step
    alembic downgrade -1
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Import the project's Base so Alembic can see every model's table metadata.
# The import of ``models`` is intentional — it ensures all ORM classes are
# registered on ``Base.metadata`` before autogenerate runs.
# ---------------------------------------------------------------------------
from app.core.database import Base  # noqa: F401
import app.core.models  # noqa: F401  — registers all models on Base.metadata

# Alembic Config object — provides access to alembic.ini values.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The MetaData object that Alembic compares against the database.
target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Override sqlalchemy.url from the DATABASE_URL environment variable.
# For Alembic (sync migrations), we replace the async driver with the
# sync equivalent so that standard ``engine_from_config`` works.
# ---------------------------------------------------------------------------
_database_url = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://aurion:aurion@localhost:5432/aurion",
)

# Alembic requires a synchronous driver.  Replace asyncpg with psycopg2.
_sync_url = _database_url.replace("+asyncpg", "+psycopg2").replace(
    "postgresql://", "postgresql+psycopg2://"
    if "+psycopg2" not in _database_url.replace("+asyncpg", "+psycopg2")
    else "postgresql://"
)

# Simpler replacement: just swap asyncpg for psycopg2
_sync_url = _database_url.replace("asyncpg", "psycopg2")

config.set_main_option("sqlalchemy.url", _sync_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Connects to the database and applies migrations directly.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
