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

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import app.core.models  # noqa: F401  — registers all models on Base.metadata
from alembic import context

# ---------------------------------------------------------------------------
# Import the project's Base so Alembic can see every model's table metadata.
# The import of ``models`` is intentional — it ensures all ORM classes are
# registered on ``Base.metadata`` before autogenerate runs.
#
# Reading DATABASE_URL via app.core.database (rather than os.getenv directly)
# means we share its normalisation logic for the JSON-envelope shape AWS RDS
# managed-secrets emit — a plain os.getenv("DATABASE_URL") here would crash
# in prod because the env var contains '{"username":"...","password":"..."}'
# not a SQLAlchemy URL.
# ---------------------------------------------------------------------------
from app.core.database import DATABASE_URL, Base  # noqa: F401

# Alembic Config object — provides access to alembic.ini values.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The MetaData object that Alembic compares against the database.
target_metadata = Base.metadata

# Alembic uses a synchronous driver; the app uses asyncpg. Swap one for the
# other so DATABASE_URL works for both.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("asyncpg", "psycopg2"))


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
