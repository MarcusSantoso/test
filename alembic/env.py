from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from dotenv import load_dotenv
import os

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# here we allow ourselves to pass interpolation vars to alembic.ini
# from the host env
load_dotenv()
section = config.config_ini_section


def _set_option(option: str, *env_keys: str, default: str = "") -> None:
    """Populate Alembic config from the first non-empty env var."""
    for key in env_keys:
        value = os.environ.get(key)
        if value:
            config.set_section_option(section, option, value)
            break
    else:
        config.set_section_option(section, option, default)


_set_option("DATABASE_HOST", "DATABASE_HOST", "POSTGRES_HOST", default="localhost")
_set_option("DATABASE_USER", "DATABASE_USER", "POSTGRES_USER", default="postgres")
_set_option("DATABASE_PASSWORD", "DATABASE_PASSWORD", "POSTGRES_PASSWORD", default="")
_set_option(
    "DATABASE_NAME",
    "DATABASE_NAME",
    "POSTGRES_DB",
    default=os.environ.get("POSTGRES_USER", "postgres"),
)

# If a single DATABASE_URL is provided (e.g. from Render), prefer it for
# the SQLAlchemy/alembic connection. This keeps compatibility with both the
# individual POSTGRES_* vars and a single DATABASE_URL value.
db_url = os.environ.get("DATABASE_URL")
if db_url:
    # Normalize common URL schemes so SQLAlchemy can locate the correct
    # dialect plugin. Some platforms (Render) provide URLs that start with
    # `postgres://` which triggers SQLAlchemy to look for
    # `sqlalchemy.dialects.postgres` (not present). Replace that with the
    # supported `postgresql://` scheme. If a fully-qualified DBAPI is
    # provided (eg `postgresql+psycopg2://`) keep it as-is.
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    # configure sqlalchemy.url for alembic
    config.set_main_option("sqlalchemy.url", db_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from src.user_service.models.user import Base
# Import the models package so all model modules register their tables
import src.user_service.models  # noqa: F401 - ensure modules are imported for metadata

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

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

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
