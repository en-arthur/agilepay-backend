"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-23

Creates every table in app/models plus the PostgreSQL enum types.

NOTE: the `rail` and `destinationstatus` enums are shared by several tables.
They are created once here and referenced with create_type=False, otherwise
CREATE TYPE would run twice and fail with DuplicateObject.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

ENUMS = {
    "accounttype": ('DEVELOPER', 'MERCHANT', 'INDIVIDUAL'),
    "kycstatus": ('NOT_STARTED', 'PENDING', 'APPROVED', 'RFI', 'FINAL_REJECTION'),
    "merchantstatus": ('PENDING', 'ACTIVE', 'SUSPENDED', 'CLOSED'),
    "keyenvironment": ('TEST', 'LIVE'),
    "rail": ('PIX', 'SPEI', 'SEPA', 'ACH', 'FEDWIRE', 'FPS', 'SWIFT'),
    "destinationstatus": ('PENDING', 'APPROVED', 'REJECTED'),
    "recipientrelationship": ('RELATIVE', 'FRIEND'),
    "transactiontype": ('OFF_RAMP', 'ON_RAMP', 'TRANSFER'),
    "transactionstatus": ('PENDING', 'AWAITING_FUNDS', 'PROCESSING', 'TRANSFERRING_STABLECOIN', 'TRADING', 'TRANSFERRING_FIAT', 'COMPLETED', 'FAILED', 'CANCELLED', 'REFUNDED'),
    "webhookdirection": ('INBOUND', 'OUTBOUND'),
}


def _enum(name: str) -> postgresql.ENUM:
    """Reference an enum type created in upgrade() without creating it again."""
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    op.create_table('merchants',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('full_name', sa.String(), nullable=False),
    sa.Column('business_name', sa.String(), nullable=True),
    sa.Column('business_type', sa.String(), nullable=True),
    sa.Column('country', sa.String(), nullable=True),
    sa.Column('lumx_customer_id', sa.String(), nullable=True),
    sa.Column('lumx_wallet_address', sa.String(), nullable=True),
    sa.Column('kyc_status', _enum("kycstatus"), nullable=True),
    sa.Column('kyc_sumsub_link', sa.String(), nullable=True),
    sa.Column('tos_accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('account_type', _enum("accounttype"), nullable=True),
    sa.Column('status', _enum("merchantstatus"), nullable=True),
    sa.Column('is_live', sa.Boolean(), nullable=True),
    sa.Column('is_sandbox', sa.Boolean(), nullable=True),
    sa.Column('tax_id', sa.String(), nullable=True),
    sa.Column('birth_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('phone', sa.String(), nullable=True),
    sa.Column('address_line1', sa.String(), nullable=True),
    sa.Column('address_city', sa.String(), nullable=True),
    sa.Column('address_state', sa.String(), nullable=True),
    sa.Column('address_postal_code', sa.String(), nullable=True),
    sa.Column('address_country', sa.String(), nullable=True),
    sa.Column('monthly_volume_usd', sa.String(), nullable=True),
    sa.Column('transaction_volume_usd', sa.String(), nullable=True),
    sa.Column('source_of_funds', sa.String(), nullable=True),
    sa.Column('professional_situation', sa.String(), nullable=True),
    sa.Column('occupation', sa.String(), nullable=True),
    sa.Column('jurisdictions', postgresql.ARRAY(sa.String()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('lumx_customer_id')
    )

    op.create_table('api_keys',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('merchant_id', sa.UUID(), nullable=False),
    sa.Column('key_prefix', sa.String(), nullable=False),
    sa.Column('key_hash', sa.String(), nullable=False),
    sa.Column('last_four_chars', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('environment', _enum("keyenvironment"), nullable=True),
    sa.Column('scopes', postgresql.ARRAY(sa.String()), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key_hash')
    )

    op.create_table('destinations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('merchant_id', sa.UUID(), nullable=False),
    sa.Column('lumx_destination_id', sa.String(), nullable=True),
    sa.Column('label', sa.String(), nullable=True),
    sa.Column('rail', _enum("rail"), nullable=False),
    sa.Column('currency', sa.String(), nullable=False),
    sa.Column('country', sa.String(), nullable=False),
    sa.Column('identifier', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('holder_name', sa.String(), nullable=False),
    sa.Column('holder_relationship', sa.String(), nullable=True),
    sa.Column('status', _enum("destinationstatus"), nullable=True),
    sa.Column('is_default', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lumx_destination_id')
    )

    op.create_table('partner_fee_configs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('merchant_id', sa.UUID(), nullable=False),
    sa.Column('lumx_fee_id', sa.String(), nullable=True),
    sa.Column('fee_rate_bps', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('flat_fee_cents', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('merchant_id')
    )

    op.create_table('recipients',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('merchant_id', sa.UUID(), nullable=False),
    sa.Column('lumx_destination_id', sa.String(), nullable=True),
    sa.Column('full_name', sa.String(), nullable=False),
    sa.Column('email', sa.String(), nullable=True),
    sa.Column('phone', sa.String(), nullable=True),
    sa.Column('relationship', _enum("recipientrelationship"), nullable=False),
    sa.Column('rail', _enum("rail"), nullable=False),
    sa.Column('currency', sa.String(), nullable=False),
    sa.Column('country', sa.String(), nullable=False),
    sa.Column('identifier', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', _enum("destinationstatus"), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lumx_destination_id')
    )

    op.create_table('payment_links',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('merchant_id', sa.UUID(), nullable=False),
    sa.Column('link_id', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=True),
    sa.Column('amount_cents', sa.Integer(), nullable=True),
    sa.Column('currency', sa.String(), nullable=True),
    sa.Column('is_fixed_amount', sa.Boolean(), nullable=True),
    sa.Column('min_amount_cents', sa.Integer(), nullable=True),
    sa.Column('max_amount_cents', sa.Integer(), nullable=True),
    sa.Column('default_destination_id', sa.UUID(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('max_uses', sa.Integer(), nullable=True),
    sa.Column('use_count', sa.Integer(), nullable=True),
    sa.Column('success_url', sa.String(), nullable=True),
    sa.Column('cancel_url', sa.String(), nullable=True),
    sa.Column('logo_url', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['default_destination_id'], ['destinations.id'], ),
    sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('link_id')
    )

    op.create_table('transactions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('merchant_id', sa.UUID(), nullable=False),
    sa.Column('destination_id', sa.UUID(), nullable=True),
    sa.Column('payment_link_id', sa.UUID(), nullable=True),
    sa.Column('recipient_id', sa.UUID(), nullable=True),
    sa.Column('charge_id', sa.String(), nullable=False),
    sa.Column('lumx_transaction_id', sa.String(), nullable=True),
    sa.Column('source_amount', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('source_currency', sa.String(), nullable=True),
    sa.Column('target_amount', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('target_currency', sa.String(), nullable=True),
    sa.Column('exchange_rate', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('lumx_exchange_rate_id', sa.String(), nullable=True),
    sa.Column('exchange_rate_locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('exchange_rate_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('final_target_amount', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('final_exchange_rate', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('platform_fee_cents', sa.String(), nullable=True),
    sa.Column('platform_fee_rate', sa.Numeric(precision=5, scale=4), nullable=True),
    sa.Column('type', _enum("transactiontype"), nullable=True),
    sa.Column('purpose', sa.String(), nullable=True),
    sa.Column('blockchain', sa.String(), nullable=True),
    sa.Column('status', _enum("transactionstatus"), nullable=True),
    sa.Column('payer_name', sa.String(), nullable=True),
    sa.Column('payer_email', sa.String(), nullable=True),
    sa.Column('payer_phone', sa.String(), nullable=True),
    sa.Column('description', sa.String(), nullable=True),
    sa.Column('reference_id', sa.String(), nullable=True),
    sa.Column('memo', sa.String(), nullable=True),
    sa.Column('tx_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('idempotency_key', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['destination_id'], ['destinations.id'], ),
    sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], ),
    sa.ForeignKeyConstraint(['payment_link_id'], ['payment_links.id'], ),
    sa.ForeignKeyConstraint(['recipient_id'], ['recipients.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('charge_id'),
    sa.UniqueConstraint('idempotency_key'),
    sa.UniqueConstraint('lumx_transaction_id')
    )

    op.create_table('webhook_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('transaction_id', sa.UUID(), nullable=True),
    sa.Column('direction', _enum("webhookdirection"), nullable=False),
    sa.Column('lumx_event_id', sa.String(), nullable=True),
    sa.Column('event_type', sa.String(), nullable=False),
    sa.Column('source_ip', sa.String(), nullable=True),
    sa.Column('endpoint', sa.String(), nullable=False),
    sa.Column('http_method', sa.String(), nullable=True),
    sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('signature_header', sa.String(), nullable=True),
    sa.Column('signature_valid', sa.Boolean(), nullable=True),
    sa.Column('response_status', sa.Integer(), nullable=True),
    sa.Column('response_body', sa.Text(), nullable=True),
    sa.Column('processing_error', sa.Text(), nullable=True),
    sa.Column('retry_count', sa.Integer(), nullable=True),
    sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lumx_event_id')
    )


def downgrade() -> None:
    op.drop_table("webhook_logs")
    op.drop_table("transactions")
    op.drop_table("payment_links")
    op.drop_table("recipients")
    op.drop_table("partner_fee_configs")
    op.drop_table("destinations")
    op.drop_table("api_keys")
    op.drop_table("merchants")
    bind = op.get_bind()
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
