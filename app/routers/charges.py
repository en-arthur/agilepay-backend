"""
Off-ramp charges — money OUT (USDC → fiat to a bank destination).

  API-key auth (SDK / legacy developers):
    POST /v1/charges
    GET  /v1/charges
    GET  /v1/charges/{id}

  JWT auth (dashboard UI — no-code merchants):
    POST /v1/charges/dashboard
    GET  /v1/charges/dashboard
    GET  /v1/charges/dashboard/balance

Merchant accounts are no-code, so they never see an API key — the dashboard
routes let them send a payout straight from the Payouts page.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.lib.auth import (
    get_api_key_context,
    get_current_merchant,
    ApiKeyContext,
    require_scope,
)
from app.models.merchant import Merchant
from app.models.transaction import Transaction
from app.services.lumx import lumx
from app.services.payouts import create_charge, fmt_charge, list_charges

router = APIRouter()


class ChargeRequest(BaseModel):
    amount:          float
    destination_id:  str
    description:     Optional[str] = None
    reference_id:    Optional[str] = None
    metadata:        Optional[dict] = None
    idempotency_key: Optional[str] = None


# ── POST /v1/charges (API key) ───────────────────────────────────────────────

@router.post("", status_code=202)
def create_charge_api(
    body: ChargeRequest,
    ctx:  ApiKeyContext = Depends(get_api_key_context),
    db:   Session = Depends(get_db),
):
    require_scope(ctx, "charges:create")

    merchant = db.query(Merchant).filter(Merchant.id == ctx.merchant_id).first()

    # KYC gate for live keys
    if ctx.environment == "LIVE" and merchant.kyc_status.value != "APPROVED":
        raise HTTPException(403, "KYC verification required for live charges")

    tx = create_charge(
        db,
        merchant,
        amount          = body.amount,
        destination_id  = body.destination_id,
        description     = body.description,
        reference_id    = body.reference_id,
        metadata        = body.metadata,
        idempotency_key = body.idempotency_key,
    )
    return fmt_charge(tx)


# ── GET /v1/charges (API key) ────────────────────────────────────────────────

@router.get("")
def list_charges_api(
    ctx:   ApiKeyContext = Depends(get_api_key_context),
    db:    Session = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
):
    require_scope(ctx, "transactions:read")
    return [fmt_charge(tx) for tx in list_charges(db, ctx.merchant_id, limit, offset)]


# ── POST /v1/charges/dashboard (JWT — no-code merchants) ─────────────────────

@router.post("/dashboard", status_code=202)
def dashboard_create_charge(
    body: ChargeRequest,
    merchant: Merchant = Depends(get_current_merchant),
    db:       Session = Depends(get_db),
):
    tx = create_charge(
        db,
        merchant,
        amount          = body.amount,
        destination_id  = body.destination_id,
        description     = body.description,
        reference_id    = body.reference_id,
        metadata        = body.metadata,
        idempotency_key = body.idempotency_key,
    )
    return fmt_charge(tx)


# ── GET /v1/charges/dashboard (JWT) ──────────────────────────────────────────

@router.get("/dashboard")
def dashboard_list_charges(
    merchant: Merchant = Depends(get_current_merchant),
    db:       Session = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
):
    return [fmt_charge(tx) for tx in list_charges(db, merchant.id, limit, offset)]


# ── GET /v1/charges/dashboard/balance (JWT) ──────────────────────────────────

@router.get("/dashboard/balance")
def dashboard_balance(merchant: Merchant = Depends(get_current_merchant)):
    """
    USDC available for payouts, read from Lumx.

    Balances are only returned by Lumx once the customer's KYC is APPROVED;
    before that (or on a network error) we report 0 instead of failing the
    page.
    """
    zero = {"currency": "USDC", "amount": "0.000000", "wallets": []}
    if not merchant.lumx_customer_id:
        return zero

    try:
        customer = lumx.get_customer(merchant.lumx_customer_id)
    except Exception:
        return zero

    wallets = customer.get("wallets") or []
    total = 0.0
    for wallet in wallets:
        for balance in wallet.get("balances") or []:
            if (balance.get("currency") or "").upper() == "USDC":
                try:
                    total += float(balance.get("amount") or 0)
                except (TypeError, ValueError):
                    pass

    return {
        "currency": "USDC",
        "amount":   f"{total:.6f}",
        "wallets":  wallets,
    }


# ── GET /v1/charges/{charge_id} (API key) ────────────────────────────────────
# Declared LAST so the static /dashboard routes above are not swallowed.

@router.get("/{charge_id}")
def get_charge(
    charge_id: str,
    ctx:  ApiKeyContext = Depends(get_api_key_context),
    db:   Session = Depends(get_db),
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
    return fmt_charge(tx)
