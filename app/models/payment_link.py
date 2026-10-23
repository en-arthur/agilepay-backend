from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid

from app.models import Base


class PaymentLink(Base):
    __tablename__ = "payment_links"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )

    link_id     = Column(String, unique=True, nullable=False)  # "lnk_xxx" — used in /pay/[linkId]
    title       = Column(String, nullable=False)
    description = Column(String)

    amount_cents     = Column(Integer)    # null = buyer enters amount
    currency         = Column(String, default="USD")
    is_fixed_amount  = Column(Boolean, default=True)
    min_amount_cents = Column(Integer)
    max_amount_cents = Column(Integer)

    default_destination_id = Column(UUID(as_uuid=True), ForeignKey("destinations.id"))

    is_active  = Column(Boolean, default=True)
    expires_at = Column(DateTime(timezone=True))
    max_uses   = Column(Integer)
    use_count  = Column(Integer, default=0)

    success_url = Column(String)
    cancel_url  = Column(String)
    logo_url    = Column(String)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    merchant     = relationship("Merchant", back_populates="payment_links")
    transactions = relationship("Transaction", back_populates="payment_link")
