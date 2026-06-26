"""SQLAlchemy async engine and session factory.

All database access goes through the async session provided here.
"""

from __future__ import annotations

import json
import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


def _resolve_database_url() -> str:
    """Return a SQLAlchemy connection URL, normalising the two prod shapes.

    Local dev (docker-compose) sets DATABASE_URL to a plain URL like
    `postgresql+asyncpg://aurion:aurion@db:5432/aurion`. The ECS task
    definition, on the other hand, injects DATABASE_URL via Secrets
    Manager — and AWS's RDS-managed master-user secret arrives as a JSON
    envelope:

        {"username": "aurion", "password": "..."}

    SQLAlchemy can't parse that. So when we detect the JSON shape, we
    combine the credentials with DB_HOST / DB_PORT / DB_NAME (non-secret
    env vars set by the task definition) and rebuild a real URL.
    """
    raw = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://aurion:aurion@localhost:5432/aurion",
    )
    if raw.lstrip().startswith("{"):
        creds = json.loads(raw)
        username = creds["username"]
        password = creds["password"]
        host = os.environ["DB_HOST"]
        port = os.getenv("DB_PORT", "5432")
        db_name = os.getenv("DB_NAME", "aurion")
        raw = (
            f"postgresql+asyncpg://{username}:{password}"
            f"@{host}:{port}/{db_name}"
        )
    return raw


DATABASE_URL = _resolve_database_url()


def _ssl_connect_args(url: str) -> dict[str, str]:
    """Force TLS on the asyncpg connection for RDS, plaintext for local dev.

    RDS enforces ``rds.force_ssl = 1``, but the URL we rebuild from the
    RDS-managed master secret (see ``_resolve_database_url``) carries no
    ``sslmode``. asyncpg defaults to a non-SSL connection, which RDS rejects
    with ``no pg_hba.conf entry for host ... no encryption`` — a latent
    fragility that surfaced as intermittent 500s when a task's connections
    churned. Pinning ``ssl=require`` here makes every connection encrypted
    regardless of how the URL was assembled (the env-var path *or* the
    rebuilt-from-JSON path), decoupling TLS from URL formatting.

    Local dev (docker-compose Postgres) has no TLS, so hosts that are clearly
    local stay plaintext. ``require`` encrypts without CA verification, which
    matches RDS's default posture and needs no cert bundle.
    """
    is_local = any(h in url for h in ("@localhost", "@127.0.0.1", "@db:", "@db/"))
    return {} if is_local else {"ssl": "require"}


engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("LOG_LEVEL", "").upper() == "DEBUG",
    pool_size=10,
    max_overflow=20,
    connect_args=_ssl_connect_args(DATABASE_URL),
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db() -> None:
    """Dispose engine. Called on shutdown."""
    await engine.dispose()
