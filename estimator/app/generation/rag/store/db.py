"""Async engine + session factory for the pgvector store.

Reuses ``Settings.DATABASE_URL`` (same host/creds as the sync Session 6
engine), swapping the driver to asyncpg — the rest of the app talks to
Postgres synchronously; only ingest/search go through this async path.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings


@lru_cache
def get_async_engine():
    url = get_settings().DATABASE_URL.replace("postgresql+psycopg", "postgresql+asyncpg")
    return create_async_engine(url, pool_pre_ping=True)


@lru_cache
def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_async_engine(), expire_on_commit=False)


async def get_db_session():
    async with get_async_sessionmaker()() as session:
        yield session
