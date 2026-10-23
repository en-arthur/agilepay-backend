from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid

from app.models import Base, WebhookDirection


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(UUID(as_uuid=True), ForeignKey("transactions.id"))

    direction     = Column(SAEnum(WebhookDirection), nullable=False)
    lumx_event_id = Column(String, unique=True)  # deduplication key
    event_type    = Column(String, nullable=False)

    source_ip        = Column(String)
    endpoint         = Column(String, nullable=False)
    http_method      = Column(String, default="POST")
    raw_payload      = Column(JSONB, nullable=False)
    signature_header = Column(String)
    signature_valid  = Column(Boolean)

    response_status  = Column(Integer)
    response_body    = Column(Text)
    processing_error = Column(Text)

    retry_count   = Column(Integer, default=0)
    next_retry_at = Column(DateTime(timezone=True))
    processed_at  = Column(DateTime(timezone=True))

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    transaction = relationship("Transaction", back_populates="webhook_logs")
