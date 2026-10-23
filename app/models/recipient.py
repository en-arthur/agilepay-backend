from sqlalchemy import Column, String, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid

from app.models import Base, Rail, DestinationStatus, RecipientRelationship


class Recipient(Base):
    __tablename__ = "recipients"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    lumx_destination_id = Column(String, unique=True)

    full_name = Column(String, nullable=False)
    email     = Column(String)
    phone     = Column(String)

    # RELATIVE or FRIEND — key compliance distinction vs SELF on Destination
    relationship = Column(SAEnum(RecipientRelationship), nullable=False)

    rail       = Column(SAEnum(Rail), nullable=False)
    currency   = Column(String, nullable=False)
    country    = Column(String, nullable=False)
    identifier = Column(JSONB, nullable=False)

    status = Column(SAEnum(DestinationStatus), default=DestinationStatus.PENDING)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    merchant    = relationship("Merchant", back_populates="recipients")
    remittances = relationship(
        "Transaction",
        back_populates="recipient",
        foreign_keys="Transaction.recipient_id",
    )
