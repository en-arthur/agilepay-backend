import enum
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# ── Enums ─────────────────────────────────────────────────────────────────────

class AccountType(str, enum.Enum):
    DEVELOPER  = "DEVELOPER"   # API keys, SDK, programmatic charges
    MERCHANT   = "MERCHANT"    # No-code: payment links + dashboard only
    INDIVIDUAL = "INDIVIDUAL"  # Remittance: fund wallet, send to recipients


class KycStatus(str, enum.Enum):
    NOT_STARTED     = "NOT_STARTED"
    PENDING         = "PENDING"
    APPROVED        = "APPROVED"
    RFI             = "RFI"
    FINAL_REJECTION = "FINAL_REJECTION"


class MerchantStatus(str, enum.Enum):
    PENDING   = "PENDING"
    ACTIVE    = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED    = "CLOSED"


class KeyEnvironment(str, enum.Enum):
    TEST = "TEST"
    LIVE = "LIVE"


class Rail(str, enum.Enum):
    PIX     = "PIX"      # Brazil  — BRL
    SPEI    = "SPEI"     # Mexico  — MXN
    SEPA    = "SEPA"     # Eurozone — EUR
    ACH     = "ACH"      # USA     — USD
    FEDWIRE = "FEDWIRE"  # USA large/same-day — USD
    FPS     = "FPS"      # UK      — GBP
    SWIFT   = "SWIFT"    # International fallback — USD


class DestinationStatus(str, enum.Enum):
    PENDING  = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RecipientRelationship(str, enum.Enum):
    RELATIVE = "RELATIVE"
    FRIEND   = "FRIEND"


class TransactionType(str, enum.Enum):
    OFF_RAMP = "OFF_RAMP"
    ON_RAMP  = "ON_RAMP"
    TRANSFER = "TRANSFER"


class TransactionStatus(str, enum.Enum):
    PENDING                 = "PENDING"
    AWAITING_FUNDS          = "AWAITING_FUNDS"
    PROCESSING              = "PROCESSING"
    TRANSFERRING_STABLECOIN = "TRANSFERRING_STABLECOIN"
    TRADING                 = "TRADING"
    TRANSFERRING_FIAT       = "TRANSFERRING_FIAT"
    COMPLETED               = "COMPLETED"
    FAILED                  = "FAILED"
    CANCELLED               = "CANCELLED"
    REFUNDED                = "REFUNDED"


class WebhookDirection(str, enum.Enum):
    INBOUND  = "INBOUND"
    OUTBOUND = "OUTBOUND"
