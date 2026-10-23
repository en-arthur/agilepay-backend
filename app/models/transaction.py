from sqlalchemy import Column, String, Boolean, DateTime, Numeric, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid

from app.models import Base, TransactionType, TransactionStatus


class Transaction(Base):
    __tablename__ = "transactions"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id     = Column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False)
    destination_id  = Column(UUID(as_uuid=True), ForeignKey("destinations.id"))
    payment_link_id = Column(UUID(as_uuid=True), ForeignKey("payment_links.id"))
    recipient_id    = Column(UUID(as_uuid=True), ForeignKey("recipients.id"))

    charge_id           = Column(String, unique=True, nullable=False)  # "chg_xxx"
    lumx_transaction_id = Column(String, unique=True)

    source_amount   = Column(Numeric(18, 6), nullable=False)
    source_currency = Column(String, default="USDC")
    target_amount   = Column(Numeric(18, 6))
    target_currency = Column(String)            # set from destination currency at creation
    exchange_rate   = Column(Numeric(18, 6))

    # Remittance — locked exchange rate fields
    lumx_exchange_rate_id    = Column(String)
    exchange_rate_locked_at  = Column(DateTime(timezone=True))
    exchange_rate_expires_at = Column(DateTime(timezone=True))
    final_target_amount      = Column(Numeric(18, 6))
    final_exchange_rate      = Column(Numeric(18, 6))

    platform_fee_cents = Column(String)
    platform_fee_rate  = Column(Numeric(5, 4))

    type       = Column(SAEnum(TransactionType), default=TransactionType.OFF_RAMP)
    purpose    = Column(String, default="TRADE_TRANSACTIONS")
    blockchain = Column(String, default="BASE")
    status     = Column(SAEnum(TransactionStatus), default=TransactionStatus.PENDING)

    payer_name  = Column(String)
    payer_email = Column(String)
    payer_phone = Column(String)

    description     = Column(String)
    reference_id    = Column(String)
    memo            = Column(String)
    # NOTE: "metadata" is reserved by SQLAlchemy's Declarative API (Base.metadata),
    # so the attribute is tx_metadata. It is serialized as "metadata" in the API.
    tx_metadata     = Column(JSONB, default=dict)
    idempotency_key = Column(String, unique=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at = Column(DateTime(timezone=True))
    failed_at    = Column(DateTime(timezone=True))

    merchant     = relationship("Merchant", back_populates="transactions")
    destination  = relationship("Destination", back_populates="transactions")
    payment_link = relationship("PaymentLink", back_populates="transactions")
    recipient    = relationship(
        "Recipient",
        back_populates="remittances",
        foreign_keys=[recipient_id],
    )
    webhook_logs = relationship("WebhookLog", back_populates="transaction")
