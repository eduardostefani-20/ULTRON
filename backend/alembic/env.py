"""Ambiente Alembic assíncrono (PostgreSQL/asyncpg ou SQLite/aiosqlite)."""

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import ultron.models  # noqa: F401 - registra as tabelas
from ultron.config import get_settings
from ultron.db import Base

config = context.config
if not config.get_main_option("sqlalchemy.url") or config.get_main_option("sqlalchemy.url").startswith("sqlite+aiosqlite:///./"):
    config.set_main_option("sqlalchemy.url", get_settings().resolved_database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata,
                      render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.",
                                           poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
