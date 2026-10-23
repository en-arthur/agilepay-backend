"""
GET /v1/transactions         — list transactions (JWT auth — dashboard)
GET /v1/transactions/{id}    — get single transaction
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.lib.auth import get_current_merchant
from app.models.merchant import Merchant
from app.models.transaction import Transaction

router = APIRouter()


def _fmt(tx: Transaction) -> dict:
    return {
        "id":                   str(tx.id),
        "charge_id":            tx.charge_id,
        "lumx_transaction_id":  tx.lumx_transaction_id,
        "type":                 tx.type.value,
        "status":               tx.status.value,
        "source_amount":        float(tx.source_amount),
        "source_currency":      tx.source_currency,
        "target_amount":        float(tx.target_amount) if tx.target_amount else None,
        "target_currency":      tx.target_currency,
        "exchange_rate":        float(tx.exchange_rate) if tx.exchange_rate else None,
        "payer_name":           tx.payer_name,
        "payer_email":          tx.payer_email,
        "description":          tx.description,
        "reference_id":         tx.reference_id,
        "destination_id":       str(tx.destination_id) if tx.destination_id else None,
        "payment_link_id":      str(tx.payment_link_id) if tx.payment_link_id else None,
        "recipient_id":         str(tx.recipient_id) if tx.recipient_id else None,
        "metadata":             tx.metadata or {},
        "created_at":           tx.created_at.isoformat(),
        "updated_at":           tx.updated_at.isoformat() if tx.updated_at else None,
        "completed_at":         tx.completed_at.isoformat() if tx.completed_at else None,
        "failed_at":            tx.failed_at.isoformat() if tx.failed_at else None,
    }


# ── GET /v1/transactions ──────────────────────────────────────────────────────

@router.get("")
def list_transactions(
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
    status: str = None,
):
    query = db.query(Transaction).filter(Transaction.merchant_id == merchant.id)
    if status:
        query = query.filter(Transaction.status == status.upper())

    txs = (
        query
        .order_by(Transaction.created_at.desc())
        .limit(min(limit, 100))
        .offset(offset)
        .all()
    )
    return [_fmt(tx) for tx in txs]


# ── GET /v1/transactions/{transaction_id} ─────────────────────────────────────

@router.get("/{transaction_id}")
def get_transaction(
    transaction_id: str,
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    tx = (
        db.query(Transaction)
        .filter(
            Transaction.id          == transaction_id,
            Transaction.merchant_id == merchant.id,
        )
        .first()
    )
    if not tx:
        raise HTTPException(404, "Transaction not found")
    return _fmt(tx)
