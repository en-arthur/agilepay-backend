"""
POST /v1/charges          — create a new off-ramp charge (DEVELOPER SDK)
GET  /v1/charges          — list charges for the authenticated API key
GET  /v1/charges/{id}     — retrieve a single charge
"""
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.lib.auth import get_api_key_context, ApiKeyContext, require_scope
from app.lib.ids import generate_charge_id
from app.models.destination import Destination
from app.models.merchant import Merchant
from app.models.transaction import Transaction
from app.services.lumx import LumxError, lumx

router = APIRouter()


class ChargeRequest(BaseModel):
    amount:          float
    destination_id:  str
    description:     Optional[str] = None
    reference_id:    Optional[str] = None
    metadata:        Optional[dict] = None
    idempotency_key: Optional[str] = None


def _fmt_charge(tx: Transaction) -> dict:
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


# ── POST /v1/charges ──────────────────────────────────────────────────────────

@router.post("", status_code=202)
def create_charge(
    body: ChargeRequest,
    ctx:  ApiKeyContext = Depends(get_api_key_context),
    db:   Session = Depends(get_db),
):
    require_scope(ctx, "charges:create")

    merchant = db.query(Merchant).filter(Merchant.id == ctx.merchant_id).first()

    # Account type gate
    if merchant.account_type.value == "MERCHANT":
        raise HTTPException(403, "Charges API not available for no-code accounts. Use payment links.")
    if merchant.account_type.value == "INDIVIDUAL":
        raise HTTPException(403, "Charges API not available for individual accounts. Use remittance.")

    # KYC gate for live keys
    if ctx.environment == "LIVE" and merchant.kyc_status.value != "APPROVED":
        raise HTTPException(403, "KYC verification required for live charges")

    # Idempotency
    if body.idempotency_key:
        existing = db.query(Transaction).filter(
            Transaction.idempotency_key == body.idempotency_key
        ).first()
        if existing:
            return _fmt_charge(existing)

    # Resolve approved destination
    destination = (
        db.query(Destination)
        .filter(
            Destination.id          == body.destination_id,
            Destination.merchant_id == ctx.merchant_id,
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
        source_amount   = body.amount,
        source_currency = "USDC",
        target_currency = destination.currency,
        type            = "OFF_RAMP",
        status          = "PENDING",
        description     = body.description,
        reference_id    = body.reference_id,
        tx_metadata     = body.metadata or {},
        idempotency_key = body.idempotency_key,
    )
    db.add(tx)
    db.flush()

    lumx_payload: dict[str, Any] = {
        "destinationId":  destination.lumx_destination_id,
        "sourceCurrency": "USDC",
        "sourceAmount":   f"{body.amount:.2f}",
        "purpose":        "TRADE_TRANSACTIONS",
        "memo":           body.reference_id or charge_id,
        "metadata": {
            "agilepay_charge_id":      charge_id,
            "agilepay_transaction_id": str(tx.id),
        },
    }

    # Let Lumx use the project's default blockchain unless one is configured —
    # hardcoding a chain that the customer has no wallet on returns
    # ACCOUNT_NOT_FOUND. Same for partner fees: only send a real UUID.
    if settings.LUMX_BLOCKCHAIN:
        lumx_payload["blockchain"] = settings.LUMX_BLOCKCHAIN
    if settings.LUMX_PARTNER_FEE_ID:
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

    return _fmt_charge(tx)


# ── GET /v1/charges ───────────────────────────────────────────────────────────

@router.get("")
def list_charges(
    ctx: ApiKeyContext = Depends(get_api_key_context),
    db:  Session = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
):
    require_scope(ctx, "transactions:read")
    txs = (
        db.query(Transaction)
        .filter(
            Transaction.merchant_id == ctx.merchant_id,
            Transaction.charge_id.like("chg_%"),
        )
        .order_by(Transaction.created_at.desc())
        .limit(min(limit, 100))
        .offset(offset)
        .all()
    )
    return [_fmt_charge(tx) for tx in txs]


# ── GET /v1/charges/{charge_id} ───────────────────────────────────────────────

@router.get("/{charge_id}")
def get_charge(
    charge_id: str,
    ctx: ApiKeyContext = Depends(get_api_key_context),
    db:  Session = Depends(get_db),
):
    require_scope(ctx, "transactions:read")
    tx = (
        db.query(Transaction)
        .filter(
            Transaction.charge_id   == charge_id,
            Transaction.merchant_id == ctx.merchant_id,
        )
        .first()
    )
    if not tx:
        raise HTTPException(404, "Charge not found")
    return _fmt_charge(tx)
