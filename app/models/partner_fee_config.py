from sqlalchemy import Column, String, Boolean, DateTime, Numeric, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid

from app.models import Base


class PartnerFeeConfig(Base):
    """
    Per-merchant partner fee override.
    When absent, the global LUMX_PARTNER_FEE_ID from config is used.
    """
    __tablename__ = "partner_fee_configs"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    lumx_fee_id      = Column(String)           # Lumx partner fee UUID
    fee_rate_bps     = Column(Numeric(6, 2))    # basis points, e.g. 50 = 0.50%
    flat_fee_cents   = Column(Integer)          # flat fee in USD cents
    is_active        = Column(Boolean, default=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    merchant = relationship("Merchant", back_populates="partner_fee_config")
