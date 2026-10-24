"""
Payout (off-ramp) service — USDC out to a bank destination.

Shared by:
  • POST /v1/charges            (API key, legacy developers)
  • POST /v1/charges/dashboard  (JWT, no-code merchants)
  • auto-settlement             (when a collection completes and the merchant
                                 has a payout destination configured)

Keeping it here (instead of in the router) means the webhook handler can
settle a collection without importing an HTTP router.
"""
from typing import Any, Optional
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.lib.ids import generate_charge_id
from app.models.destination import Destination
from app.models.merchant import Merchant
from app.models.transaction import Transaction
from app.services.lumx import LumxError, lumx


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def fmt_charge(tx: Transaction) -> dict:
    return {
        "id":                   tx.charge_id,
        "transaction_id":       str(tx.id),
        "status":               tx.status.value,
        "amount":               float(tx.source_amount),
        "currency":             tx.source_currency,
        "settlement_currency":  tx.target_currency,
        "description":          tx.description,
        "reference_id":         tx.reference_id,
        "lumx_transaction_id":  tx.lumx_transaction_id,
        "created_at":           tx.created_at.isoformat(),
        "updated_at":           tx.updated_at.isoformat() if tx.updated_at else None,
        "completed_at":         tx.completed_at.isoformat() if tx.completed_at else None,
    }


def create_charge(
    db: Session,
    merchant: Merchant,
    *,
    amount: float,
    destination_id: str,
    description: Optional[str] = None,
    reference_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
) -> Transaction:
    """Debit the merchant's USDC balance and pay out to an approved destination."""
    if amount is None or float(amount) <= 0:
        raise HTTPException(400, "amount must be greater than zero")

    # Individuals use the remittance flow instead.
    if merchant.account_type.value == "INDIVIDUAL":
        raise HTTPException(403, "Charges API not available for individual accounts. Use remittance.")

    # Idempotency — scoped to the merchant so two merchants can reuse a key.
    if idempotency_key:
        existing = (
            db.query(Transaction)
            .filter(
                Transaction.merchant_id == merchant.id,
                Transaction.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing:
            return existing

    destination = (
        db.query(Destination)
        .filter(
            Destination.id          == destination_id,
            Destination.merchant_id == merchant.id,
            Destination.status      == "APPROVED",
        )
        .first()
    )
    if not destination:
        raise HTTPException(404, "Destination not found or not yet approved")

    charge_id = generate_charge_id()

    tx = Transaction(
        merchant_id     = merchant.id,
        destination_id  = destination.id,
        charge_id       = charge_id,
        source_amount   = amount,
        source_currency = "USDC",
        target_currency = destination.currency,
        type            = "OFF_RAMP",
        status          = "PENDING",
        description     = description,
        reference_id    = reference_id,
        tx_metadata     = metadata or {},
        idempotency_key = idempotency_key,
    )
    db.add(tx)
    db.flush()

    lumx_payload: dict = {
        "destinationId":  destination.lumx_destination_id,
        "sourceCurrency": "USDC",
        "sourceAmount":   f"{float(amount):.2f}",
        "purpose":        "TRADE_TRANSACTIONS",
        "memo":           reference_id or charge_id,
        "metadata": {
            "agilepay_charge_id":      charge_id,
            "agilepay_transaction_id": str(tx.id),
            **(metadata or {}),
        },
    }

    # Let Lumx use the project's default blockchain unless one is configured —
    # hardcoding a chain that the customer has no wallet on returns
    # ACCOUNT_NOT_FOUND. Same for partner fees: only send a real UUID.
    if settings.LUMX_BLOCKCHAIN:
        lumx_payload["blockchain"] = settings.LUMX_BLOCKCHAIN
    if _is_uuid(settings.LUMX_PARTNER_FEE_ID):
        lumx_payload["partnerFeeId"] = settings.LUMX_PARTNER_FEE_ID

    try:
        lumx_response = lumx.create_offramp(
            payload=lumx_payload,
            idempotency_key=str(uuid.uuid4()),
        )
    except LumxError as exc:
        tx.status = "FAILED"
        db.commit()
        raise HTTPException(
            502,
            f"Payment network rejected the charge: {exc.body[:400]}",
        )
    except Exception:
        tx.status = "FAILED"
        db.commit()
        raise HTTPException(502, "Payment network unavailable")

    tx.lumx_transaction_id = lumx_response["id"]
    tx.status = "PROCESSING"
    db.commit()
    db.refresh(tx)
    return tx


def list_charges(db: Session, merchant_id, limit: int = 20, offset: int = 0) -> list[Transaction]:
    return (
        db.query(Transaction)
        .filter(
            Transaction.merchant_id == merchant_id,
            Transaction.charge_id.like("chg_%"),
        )
        .order_by(Transaction.created_at.desc())
        .limit(min(limit, 100))
        .offset(offset)
        .all()
    )
