import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Load application models so Alembic sees them ─────────────────────────────
from app.models import Base  # noqa: F401
from app.models.merchant import Merchant  # noqa: F401
from app.models.api_key import ApiKey  # noqa: F401
from app.models.destination import Destination  # noqa: F401
from app.models.recipient import Recipient  # noqa: F401
from app.models.transaction import Transaction  # noqa: F401
from app.models.payment_link import PaymentLink  # noqa: F401
from app.models.partner_fee_config import PartnerFeeConfig  # noqa: F401
from app.models.webhook_log import WebhookLog  # noqa: F401

# ── Alembic config ────────────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Override sqlalchemy.url from DATABASE_URL env var.
# configparser treats "%" as interpolation syntax, so a percent-encoded
# password (e.g. "@" -> "%40") must be escaped or set_main_option raises
# "invalid interpolation syntax". Escaping with "%%" is undone when the
# value is read back via get_main_option()/get_section().
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (SQL script mode)."""
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
    """Run migrations with a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
