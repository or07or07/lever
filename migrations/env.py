"""Alembic environment configuration for MechFix.

Reads DATABASE_URL from .env (via python-dotenv) or environment variables,
ensuring the same connection settings are used in both the app and migrations.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from alembic import context

# ---------------------------------------------------------------------------
# Add project root to path so we can import app modules
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file if present (mirrors what pydantic-settings does in config.py)
try:
    from dotenv import load_dotenv
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        load_dotenv(str(env_file))
except ImportError:
    pass  # python-dotenv may not be installed in the migration environment

# ---------------------------------------------------------------------------
# Import app models so Alembic can detect schema changes
# ---------------------------------------------------------------------------
from database import Base  # noqa: E402
import models  # noqa: E402, F401  — registers all ORM models with Base.metadata

# ---------------------------------------------------------------------------
# Alembic config object
# ---------------------------------------------------------------------------
config = context.config

# Override the sqlalchemy.url with the app's DATABASE_URL env var
# This means alembic.ini's sqlalchemy.url is just a fallback default.
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The MetaData object containing all table definitions
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Run migrations offline (generate SQL without a live DB connection)
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL — no Engine is needed.
    Useful for generating SQL scripts to review before applying.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Run migrations online (apply directly to a live DB connection)
# ---------------------------------------------------------------------------
def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connects to the database directly."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
