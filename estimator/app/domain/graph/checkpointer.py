"""Postgres-backed checkpointer for the estimation graph (Session 13).

Reuses the project's existing Postgres (the pgvector instance) — no new
infrastructure. ``AsyncPostgresSaver`` manages its own tables (``setup()``
creates them idempotently on first run) and coexists fine with the
embeddings/documents tables.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import Settings, get_settings


def plain_postgres_dsn(database_url: str) -> str:
    """Strip the SQLAlchemy driver token, leaving a bare ``postgresql://...`` DSN.

    ``Settings.DATABASE_URL`` carries a driver (``+psycopg``) for SQLAlchemy;
    ``AsyncPostgresSaver`` speaks psycopg3 directly over a plain DSN.
    """
    for token in ("+psycopg", "+asyncpg"):
        if token in database_url:
            return database_url.replace(token, "")
    return database_url


@asynccontextmanager
async def open_checkpointer(settings: Settings | None = None) -> AsyncIterator[AsyncPostgresSaver]:
    """Open the checkpointer for the lifetime of the app, creating its tables once."""
    dsn = plain_postgres_dsn((settings or get_settings()).DATABASE_URL)
    async with AsyncPostgresSaver.from_conn_string(dsn) as checkpointer:
        await checkpointer.setup()
        yield checkpointer
