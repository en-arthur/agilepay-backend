"""
Collection (on-ramp) service — money coming IN from a payer.

Shared by:
  • POST /v1/collections        (developer API, API-key auth)
  • POST /pay/{link_id}         (public hosted checkout)

Lumx `POST /transactions/on-ramp` returns the payment instructions the payer
must use (bank transfer details or a PIX brCode). We persist that object
verbatim in `payment_details` so it can be rendered again at any time.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.lib.ids import generate_collection_id
from app.models.collection import Collection
from app.models.merchant import Merchant
from app.services.lumx import LumxError, lumx


# Which rail can carry which source currency. Lumx on-ramp supports:
# PIX (BRL), SWIFT (USD), SEPA (EUR), ACH/FEDWIRE (USD), SPEI (MXN), FPS (GBP).
RAIL_BY_CURRENCY: dict[str, list[str]] = {
    "USD": ["SWIFT", "ACH", "FEDWIRE"],
    "GBP": ["FPS"],
    "EUR": ["SEPA"],
    "MXN": ["SPEI"],
    "BRL": ["PIX"],
}

DEFAULT_RAIL: dict[str, str] = {
    "USD": "SWIFT",
    "GBP": "FPS",
    "EUR": "SEPA",
    "MXN": "SPEI",
    "BRL": "PIX",
}

# Lumx on-ramp `purpose` enum (note: different from the off-ramp enum).
ALLOWED_PURPOSES = {
    "PERSONAL_ACCOUNT",
    "INVESTMENT",
    "REAL_ESTATE",
    "TRADE_TRANSACTIONS",
    "TAX",
    "LOAN",
    "BILLS",
    "EXPENSES_REIMBURSEMENT",
    "PROFESSIONAL_SERVICES",
}
DEFAULT_PURPOSE = "PROFESSIONAL_SERVICES"


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def resolve_rail(currency: str, rail: Optional[str]) -> str:
    """Validate/normalise the rail for a source currency."""
    currency = currency.upper()
    allowed = RAIL_BY_CURRENCY.get(currency)
    if not allowed:
        raise HTTPException(
            400,
            f"Unsupported collection currency '{currency}'. "
            f"Supported: {', '.join(sorted(RAIL_BY_CURRENCY))}",
        )
    if not rail:
        return DEFAULT_RAIL[currency]
    rail = rail.upper()
    if rail not in allowed:
        raise HTTPException(
            400,
            f"Rail '{rail}' cannot carry {currency}. Use one of: {', '.join(allowed)}",
        )
    return rail


def fmt(collection: Collection) -> dict:
    return {
        "id":               collection.collection_id,
        "status":           collection.status,
        "rail":             collection.rail,
        "amount":           float(collection.source_amount),
        "currency":         collection.source_currency,
        "target_currency":  collection.target_currency,
        "target_amount":    float(collection.target_amount) if collection.target_amount else None,
        "exchange_rate":    float(collection.exchange_rate) if collection.exchange_rate else None,
        "purpose":          collection.purpose,
        "reference_id":     collection.reference_id,
        "description":      collection.description,
        "payer_name":       collection.payer_name,
        "payer_email":      collection.payer_email,
        "payment":          collection.payment_details or {},
        "metadata":         collection.tx_metadata or {},
        "created_at":       collection.created_at.isoformat() if collection.created_at else None,
        "updated_at":       collection.updated_at.isoformat() if collection.updated_at else None,
        "completed_at":     collection.completed_at.isoformat() if collection.completed_at else None,
    }


def create_collection(
    db: Session,
    merchant: Merchant,
    *,
    amount: float,
    currency: str = "USD",
    rail: Optional[str] = None,
    purpose: Optional[str] = None,
    reference_id: Optional[str] = None,
    description: Optional[str] = None,
    payer_name: Optional[str] = None,
    payer_email: Optional[str] = None,
    payer_phone: Optional[str] = None,
    payment_link_id=None,
    idempotency_key: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Collection:
    """Create a Lumx on-ramp and persist it as a Collection."""
    currency = (currency or "USD").upper()
    rail = resolve_rail(currency, rail)

    purpose = (purpose or DEFAULT_PURPOSE).upper()
    if purpose not in ALLOWED_PURPOSES:
        raise HTTPException(
            400,
            f"Unsupported purpose '{purpose}'. Use one of: {', '.join(sorted(ALLOWED_PURPOSES))}",
        )

    if amount is None or float(amount) <= 0:
        raise HTTPException(400, "amount must be greater than zero")

    if not merchant.lumx_customer_id:
        raise HTTPException(
            409,
            "Merchant has no Lumx customer yet — complete onboarding/KYC first",
        )

    # Idempotent replay
    if idempotency_key:
        existing = (
            db.query(Collection)
            .filter(
                Collection.merchant_id == merchant.id,
                Collection.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing:
            return existing

    collection = Collection(
        merchant_id     = merchant.id,
        collection_id   = generate_collection_id(),
        payment_link_id = payment_link_id,
        status          = "PENDING",
        rail            = rail,
        source_currency = currency,
        source_amount   = Decimal(str(round(float(amount), 2))),
        target_currency = "USDC",
        purpose         = purpose,
        reference_id    = reference_id,
        description     = description,
        payer_name      = payer_name,
        payer_email     = payer_email,
        payer_phone     = payer_phone,
        payment_details = {},
        idempotency_key = idempotency_key,
        tx_metadata     = metadata or {},
    )
    db.add(collection)
    db.flush()

    payload: dict[str, Any] = {
        "customerId":     merchant.lumx_customer_id,
        "rail":           rail,
        "sourceCurrency": currency,
        "sourceAmount":   f"{float(amount):.2f}",
        "targetCurrency": "USDC",
        "purpose":        purpose,
        "metadata": {
            "agilepay_collection_id": collection.collection_id,
            "agilepay_merchant_id":   str(merchant.id),
            **(metadata or {}),
        },
    }
    # Same rules as charges: only send a blockchain the project has wallets on,
    # and only a partner-fee UUID Lumx will accept.
    if settings.LUMX_BLOCKCHAIN:
        payload["blockchain"] = settings.LUMX_BLOCKCHAIN
    if _is_uuid(settings.LUMX_PARTNER_FEE_ID):
        payload["partnerFeeId"] = settings.LUMX_PARTNER_FEE_ID

    try:
        response = lumx.create_onramp(
            payload=payload,
            idempotency_key=str(uuid.uuid4()),
        )
    except LumxError as exc:
        collection.status = "FAILED"
        collection.failed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            502,
            f"Payment network rejected the collection: {exc.body[:400]}",
        )
    except Exception:
        collection.status = "FAILED"
        collection.failed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(502, "Payment network unavailable. Please try again.")

    state = response.get("state") or {}
    collection.lumx_transaction_id = response.get("id")
    collection.status              = (state.get("status") or "AWAITING_FUNDS").upper()
    collection.payment_details     = state.get("payment") or {}
    db.commit()
    db.refresh(collection)
    return collection


def refresh_collection(db: Session, collection: Collection) -> Collection:
    """
    Best-effort status sync from Lumx.

    Webhooks are the primary update path, but polling this endpoint must also
    work (sandbox without webhooks, or a delayed delivery).
    """
    if not collection.lumx_transaction_id:
        return collection
    if collection.status in {"COMPLETED", "FAILED", "EXPIRED", "CANCELLED"}:
        return collection
    try:
        response = lumx.get_transaction(collection.lumx_transaction_id)
    except Exception:
        return collection

    state = response.get("state") or {}
    status = (state.get("status") or "").upper()
    if status:
        collection.status = status
    payment = state.get("payment")
    if payment:
        collection.payment_details = payment

    receipt = state.get("receipt") or {}
    target = receipt.get("finalTargetAmount")
    if target:
        try:
            collection.target_amount = Decimal(str(target))
        except Exception:
            pass
    rate = receipt.get("finalExchangeRate")
    if rate:
        try:
            collection.exchange_rate = Decimal(str(rate))
        except Exception:
            pass

    if collection.status == "COMPLETED" and not collection.completed_at:
        collection.completed_at = datetime.now(timezone.utc)
    if collection.status in {"FAILED", "EXPIRED"} and not collection.failed_at:
        collection.failed_at = datetime.now(timezone.utc)

    db.commit()
    return collection
