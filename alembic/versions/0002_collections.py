"""collections (fiat on-ramp)

Revision ID: 0002_collections
Revises: 0001_initial
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_collections"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_id", sa.String(), nullable=False),
        sa.Column("lumx_transaction_id", sa.String(), nullable=True),
        sa.Column("payment_link_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="AWAITING_FUNDS"),
        sa.Column("rail", sa.String(), nullable=False),
        sa.Column("source_currency", sa.String(), nullable=False),
        sa.Column("source_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("target_currency", sa.String(), server_default="USDC"),
        sa.Column("target_amount", sa.Numeric(18, 6), nullable=True),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=True),
        sa.Column("purpose", sa.String(), server_default="PROFESSIONAL_SERVICES"),
        sa.Column("reference_id", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("payer_name", sa.String(), nullable=True),
        sa.Column("payer_email", sa.String(), nullable=True),
        sa.Column("payer_phone", sa.String(), nullable=True),
        sa.Column("payment_details", postgresql.JSONB(), server_default="{}"),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("tx_metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payment_link_id"], ["payment_links.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_id"),
        sa.UniqueConstraint("lumx_transaction_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_collections_merchant_id", "collections", ["merchant_id"])
    op.create_index("ix_collections_status", "collections", ["status"])
    op.create_index("ix_collections_payment_link_id", "collections", ["payment_link_id"])


def downgrade() -> None:
    op.drop_index("ix_collections_payment_link_id", table_name="collections")
    op.drop_index("ix_collections_status", table_name="collections")
    op.drop_index("ix_collections_merchant_id", table_name="collections")
    op.drop_table("collections")
