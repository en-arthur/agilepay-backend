from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid

from app.models import Base, Rail, DestinationStatus


class Destination(Base):
    __tablename__ = "destinations"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    lumx_destination_id = Column(String, unique=True)

    label    = Column(String)
    rail     = Column(SAEnum(Rail), nullable=False)
    currency = Column(String, nullable=False)   # ISO 4217
    country  = Column(String, nullable=False)   # ISO 3166-1 alpha-2

    # Flexible per-rail identifier blob — mirrors Lumx payload structure
    # PIX:   {"keyType": "EMAIL", "keyValue": "..."}
    # SPEI:  {"clabe": "..."}
    # SEPA:  {"iban": "...", "bic": "..."}
    # ACH:   {"routingNumber": "...", "accountNumber": "...", "accountType": "CHECKING"}
    # FPS:   {"sortCode": "...", "accountNumber": "..."}
    # SWIFT: {"accountNumber": "...", "swiftCode": "...", "bankName": "..."}
    identifier = Column(JSONB, nullable=False)

    holder_name         = Column(String, nullable=False)
    holder_relationship = Column(String, default="SELF")

    status     = Column(SAEnum(DestinationStatus), default=DestinationStatus.PENDING)
    is_default = Column(Boolean, default=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    merchant     = relationship("Merchant", back_populates="destinations")
    transactions = relationship("Transaction", back_populates="destination")
