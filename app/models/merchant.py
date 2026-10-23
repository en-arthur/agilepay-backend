from sqlalchemy import Column, String, Boolean, DateTime, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid

from app.models import Base, AccountType, KycStatus, MerchantStatus


class Merchant(Base):
    __tablename__ = "merchants"

    # id = Supabase Auth user UUID — set explicitly on insert
    id = Column(UUID(as_uuid=True), primary_key=True)

    email         = Column(String, unique=True, nullable=False)
    full_name     = Column(String, nullable=False)
    business_name = Column(String)
    business_type = Column(String, default="INDIVIDUAL")
    country       = Column(String, default="GH")

    # Lumx
    lumx_customer_id    = Column(String, unique=True)
    lumx_wallet_address = Column(String)

    # KYC
    kyc_status      = Column(SAEnum(KycStatus), default=KycStatus.NOT_STARTED)
    kyc_sumsub_link = Column(String)
    tos_accepted_at = Column(DateTime(timezone=True))

    # Account flags
    account_type = Column(SAEnum(AccountType), default=AccountType.MERCHANT)
    status       = Column(SAEnum(MerchantStatus), default=MerchantStatus.PENDING)
    is_live      = Column(Boolean, default=False)
    is_sandbox   = Column(Boolean, default=True)

    # INDIVIDUAL remittance fields (null for DEVELOPER / MERCHANT)
    tax_id                 = Column(String)
    birth_date             = Column(DateTime(timezone=True))
    phone                  = Column(String)
    address_line1          = Column(String)
    address_city           = Column(String)
    address_state          = Column(String)
    address_postal_code    = Column(String)
    address_country        = Column(String)
    monthly_volume_usd     = Column(String)
    transaction_volume_usd = Column(String)
    source_of_funds        = Column(String)
    professional_situation = Column(String)
    occupation             = Column(String)
    jurisdictions          = Column(ARRAY(String), default=list)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relations
    api_keys           = relationship("ApiKey", back_populates="merchant", cascade="all, delete")
    destinations       = relationship("Destination", back_populates="merchant", cascade="all, delete")
    transactions       = relationship("Transaction", back_populates="merchant")
    collections        = relationship("Collection", back_populates="merchant", cascade="all, delete")
    payment_links      = relationship("PaymentLink", back_populates="merchant", cascade="all, delete")
    partner_fee_config = relationship(
        "PartnerFeeConfig", back_populates="merchant", uselist=False, cascade="all, delete"
    )
    recipients = relationship("Recipient", back_populates="merchant", cascade="all, delete")
