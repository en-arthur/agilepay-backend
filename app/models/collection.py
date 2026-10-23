from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid

from app.models import Base


class Collection(Base):
    """
    A fiat collection (on-ramp) — money coming IN from a payer.

    Created by POST /v1/collections (API key) or by the public hosted checkout
    (POST /pay/{link_id}). Lumx returns the bank details / PIX code the payer
    must use; those are stored verbatim in `payment_details` so the checkout
    page can render them again on reload.

    Lifecycle (driven by Lumx `onramp.*` webhooks):
        AWAITING_FUNDS -> PROCESSING -> COMPLETED | FAILED | EXPIRED
    """
    __tablename__ = "collections"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )

    collection_id       = Column(String, unique=True, nullable=False)   # "col_xxx"
    lumx_transaction_id = Column(String, unique=True)

    payment_link_id = Column(
        UUID(as_uuid=True),
        ForeignKey("payment_links.id", ondelete="SET NULL"),
    )

    status = Column(String, default="AWAITING_FUNDS", nullable=False)

    rail            = Column(String, nullable=False)     # SWIFT | FPS | SEPA | SPEI | ACH | FEDWIRE | PIX
    source_currency = Column(String, nullable=False)     # what the payer sends
    source_amount   = Column(Numeric(18, 2), nullable=False)
    target_currency = Column(String, default="USDC")
    target_amount   = Column(Numeric(18, 6))             # USDC credited on success
    exchange_rate   = Column(Numeric(18, 6))

    purpose      = Column(String, default="PROFESSIONAL_SERVICES")
    reference_id = Column(String)
    description  = Column(String)

    payer_name  = Column(String)
    payer_email = Column(String)
    payer_phone = Column(String)

    # Exactly the `state.payment` object Lumx returned:
    #   { rail, identifier: {...}, holder: {...}, bank: {...}, memo }
    # or { rail: "PIX", brCode: "000201..." }
    payment_details = Column(JSONB, default=dict)

    idempotency_key = Column(String, unique=True)
    tx_metadata     = Column(JSONB, default=dict)

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

    merchant     = relationship("Merchant", back_populates="collections")
    payment_link = relationship("PaymentLink", back_populates="collections")
