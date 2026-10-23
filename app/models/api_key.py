from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid

from app.models import Base, KeyEnvironment


class ApiKey(Base):
    __tablename__ = "api_keys"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Full key shown ONCE at creation — only prefix + bcrypt hash stored
    key_prefix      = Column(String, nullable=False)          # "sk_live_" | "sk_test_"
    key_hash        = Column(String, unique=True, nullable=False)  # bcrypt hash
    last_four_chars = Column(String, nullable=False)          # for UI display

    name        = Column(String)
    environment = Column(SAEnum(KeyEnvironment), default=KeyEnvironment.TEST)
    scopes      = Column(ARRAY(String), default=list)
    is_active   = Column(Boolean, default=True)
    last_used_at = Column(DateTime(timezone=True))
    expires_at   = Column(DateTime(timezone=True))

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    revoked_at = Column(DateTime(timezone=True))

    merchant = relationship("Merchant", back_populates="api_keys")
